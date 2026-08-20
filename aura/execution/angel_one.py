from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from aura.domain.models import Fill, OrderRequest, OrderStatus, OrderType, Side, TimeInForce
from aura.execution.broker import BrokerAdapter
from aura.execution.demo_guard import LiveTradingDisabledError
from aura.execution.reconciliation import BrokerOrderSnapshot, BrokerPositionSnapshot
from aura.execution.state import is_terminal_order_status


class SmartApiClient(Protocol):
    """Narrow contract implemented by Angel One's official SmartConnect client."""

    def getProfile(self, refresh_token: str) -> Any: ...

    def orderBook(self) -> Any: ...

    def tradeBook(self) -> Any: ...

    def position(self) -> Any: ...

    def ltpData(self, exchange: str, trading_symbol: str, symbol_token: str) -> Any: ...


@dataclass(slots=True, frozen=True)
class AngelOneSessionCredentials:
    """Short-lived SmartAPI session material supplied by the operator.

    AURA deliberately does not accept a PIN or TOTP seed. Session generation must
    happen through the user's official Angel One flow; only the resulting tokens
    are injected into this adapter.
    """

    api_key: str = field(repr=False)
    client_code: str
    jwt_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    feed_token: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        required = {
            "api_key": self.api_key,
            "client_code": self.client_code,
            "jwt_token": self.jwt_token,
            "refresh_token": self.refresh_token,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(f"missing Angel One session fields: {', '.join(missing)}")


def load_angel_one_session_from_env() -> AngelOneSessionCredentials:
    """Load an already-authorized SmartAPI session without logging any secret."""

    values = {
        "api_key": os.environ.get("AURA_ANGEL_ONE_API_KEY", "").strip(),
        "client_code": os.environ.get("AURA_ANGEL_ONE_CLIENT_CODE", "").strip(),
        "jwt_token": os.environ.get("AURA_ANGEL_ONE_JWT_TOKEN", "").strip(),
        "refresh_token": os.environ.get("AURA_ANGEL_ONE_REFRESH_TOKEN", "").strip(),
        "feed_token": os.environ.get("AURA_ANGEL_ONE_FEED_TOKEN", "").strip(),
    }
    missing = [
        name
        for name, value in values.items()
        if name != "feed_token" and not value
    ]
    if missing:
        env_names = ", ".join(f"AURA_ANGEL_ONE_{name.upper()}" for name in missing)
        raise RuntimeError(f"missing Angel One environment values: {env_names}")
    return AngelOneSessionCredentials(**values)


def create_official_smartapi_client(
    credentials: AngelOneSessionCredentials,
) -> SmartApiClient:
    """Create the optional official SDK client from pre-authorized tokens."""

    try:
        from SmartApi import SmartConnect
    except ImportError as exc:  # pragma: no cover - depends on optional vendor package
        raise RuntimeError(
            "install the official smartapi-python package to use Angel One"
        ) from exc
    return SmartConnect(
        api_key=credentials.api_key,
        access_token=credentials.jwt_token,
        refresh_token=credentials.refresh_token,
        feed_token=credentials.feed_token or None,
        userId=credentials.client_code,
    )


@dataclass(slots=True, frozen=True)
class AngelOneRoute:
    symbol_token: str
    trading_symbol: str
    exchange: str
    product_type: str = "INTRADAY"
    variety: str = "NORMAL"
    scrip_consent: bool = False

    def __post_init__(self) -> None:
        required = (self.symbol_token, self.trading_symbol, self.exchange)
        if any(not value.strip() for value in required):
            raise ValueError("Angel One route token, trading symbol and exchange are required")
        if self.exchange not in {"NSE", "BSE", "NFO", "BFO", "MCX"}:
            raise ValueError(f"unsupported Angel One exchange: {self.exchange}")


class AngelOneReadOnlyBroker(BrokerAdapter):
    """SmartAPI account-data and reconciliation adapter with execution locked.

    Angel One does not provide AURA with a production-equivalent public sandbox.
    Until credential-backed static-IP, order acknowledgement, fill and restart
    reconciliation evidence exists, order submission and cancellation always fail
    closed. Payload construction is exposed for deterministic conformance testing.
    """

    name = "ANGEL_ONE_SMARTAPI_READ_ONLY"

    def __init__(
        self,
        client: SmartApiClient,
        credentials: AngelOneSessionCredentials,
        routes: Mapping[str, AngelOneRoute],
        *,
        recovered_orders: Mapping[str, OrderRequest] | None = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.client = client
        self.credentials = credentials
        self.routes = dict(routes)
        self.poll_interval_seconds = poll_interval_seconds
        self._connected = False
        self._orders_by_broker_id = dict(recovered_orders or {})
        self._seen_trade_ids: set[str] = set()
        self._symbol_by_native_route = {
            (route.exchange, route.trading_symbol): symbol
            for symbol, route in self.routes.items()
        }

    async def connect(self) -> None:
        response = await asyncio.to_thread(
            self.client.getProfile,
            self.credentials.refresh_token,
        )
        profile = _response_data(response, "Angel One profile")
        if not isinstance(profile, dict):
            raise TypeError("Angel One profile response must contain an object")
        actual = str(profile.get("clientcode") or profile.get("clientCode") or "").strip()
        if not actual:
            raise RuntimeError("Angel One profile response is missing client code")
        if actual != self.credentials.client_code:
            raise RuntimeError(
                f"Angel One session client mismatch: expected {self.credentials.client_code}, got {actual}"
            )
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def submit_order(self, order: OrderRequest) -> str:
        self._require_connected()
        self.prepare_order_payload(order)
        raise LiveTradingDisabledError(
            "Angel One order submission is locked until credential-backed broker "
            "conformance and controlled-live phase gates pass"
        )

    async def cancel_order(self, broker_order_id: str) -> None:
        self._require_connected()
        if not broker_order_id.strip():
            raise ValueError("Angel One broker order id is required")
        raise LiveTradingDisabledError(
            "Angel One cancellation is locked with order submission until broker "
            "conformance and controlled-live phase gates pass"
        )

    def prepare_order_payload(self, order: OrderRequest) -> dict[str, str]:
        if order.venue not in {"ANGEL_ONE", "ANGEL_ONE_SMARTAPI"}:
            raise ValueError(f"order venue is not Angel One: {order.venue}")
        route = self.routes.get(order.symbol)
        if route is None:
            raise KeyError(f"missing Angel One route for {order.symbol}")
        quantity = _integer_quantity(order.quantity)
        order_type, price, trigger = _order_fields(order)
        payload = {
            "variety": route.variety,
            "tradingsymbol": route.trading_symbol,
            "symboltoken": route.symbol_token,
            "transactiontype": order.side.value,
            "exchange": route.exchange,
            "ordertype": order_type,
            "producttype": route.product_type,
            "duration": "IOC" if order.time_in_force == TimeInForce.IOC else "DAY",
            "price": price,
            "triggerprice": trigger,
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity),
            "ordertag": _order_tag(order.client_order_id),
        }
        if route.scrip_consent:
            payload["scripconsent"] = "yes"
        return payload

    async def ltp(self, symbol: str) -> Decimal:
        self._require_connected()
        route = self.routes.get(symbol)
        if route is None:
            raise KeyError(f"missing Angel One route for {symbol}")
        response = await asyncio.to_thread(
            self.client.ltpData,
            route.exchange,
            route.trading_symbol,
            route.symbol_token,
        )
        data = _response_data(response, "Angel One LTP")
        if not isinstance(data, dict):
            raise TypeError("Angel One LTP response must contain an object")
        price = Decimal(str(data.get("ltp", 0)))
        if price <= 0:
            raise RuntimeError(f"Angel One returned non-positive LTP for {symbol}")
        return price

    def open_order_snapshots(self) -> list[BrokerOrderSnapshot]:
        self._require_connected()
        rows = _response_rows(self.client.orderBook(), "Angel One order book")
        snapshots: list[BrokerOrderSnapshot] = []
        for row in rows:
            status = _order_status(row.get("orderstatus") or row.get("status"))
            if is_terminal_order_status(status):
                continue
            broker_order_id = str(row.get("orderid", "")).strip()
            quantity = Decimal(str(row.get("quantity", 0)))
            if not broker_order_id or quantity <= 0:
                continue
            mapped = self._orders_by_broker_id.get(broker_order_id)
            filled = Decimal(str(row.get("filledshares", 0)))
            if filled < 0 or filled > quantity:
                raise RuntimeError(
                    f"Angel One order {broker_order_id} has invalid filled quantity "
                    f"{filled} for requested {quantity}"
                )
            snapshots.append(
                BrokerOrderSnapshot(
                    broker_order_id=broker_order_id,
                    client_order_id=(
                        mapped.client_order_id
                        if mapped is not None
                        else f"external-angel-one:{broker_order_id}"
                    ),
                    symbol=(mapped.symbol if mapped is not None else self._native_symbol(row)),
                    side=(
                        mapped.side
                        if mapped is not None
                        else Side(str(row.get("transactiontype", "")).upper())
                    ),
                    quantity=quantity,
                    filled_quantity=filled,
                    status=status,
                )
            )
        return snapshots

    def position_snapshots(self) -> list[BrokerPositionSnapshot]:
        self._require_connected()
        rows = _response_rows(self.client.position(), "Angel One positions")
        quantities: dict[str, Decimal] = {}
        for row in rows:
            quantity = Decimal(str(row.get("netqty", row.get("netquantity", 0))))
            if quantity == 0:
                continue
            symbol = self._native_symbol(row)
            quantities[symbol] = quantities.get(symbol, Decimal(0)) + quantity
        return [
            BrokerPositionSnapshot(symbol=symbol, quantity=quantity)
            for symbol, quantity in sorted(quantities.items())
            if quantity != 0
        ]

    async def fills(self) -> AsyncIterator[Fill]:
        while self._connected:
            response = await asyncio.to_thread(self.client.tradeBook)
            for row in _response_rows(response, "Angel One trade book"):
                trade_id = str(
                    row.get("tradeid")
                    or row.get("exchtradeid")
                    or ""
                ).strip()
                broker_order_id = str(row.get("orderid", "")).strip()
                if not trade_id or trade_id in self._seen_trade_ids:
                    continue
                order = self._orders_by_broker_id.get(broker_order_id)
                if order is None:
                    continue
                quantity = Decimal(str(row.get("fillsize", row.get("filledshares", 0))))
                price = Decimal(str(row.get("fillprice", row.get("averageprice", 0))))
                if quantity <= 0 or price <= 0:
                    raise RuntimeError(f"invalid Angel One trade row: {row!r}")
                self._seen_trade_ids.add(trade_id)
                yield Fill(
                    fill_id=f"angel-one:{trade_id}",
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=Side(str(row.get("transactiontype", order.side.value)).upper()),
                    quantity=quantity,
                    price=price,
                    fee=Decimal(0),
                    timestamp=_timestamp(
                        row.get("filltime")
                        or row.get("exchtime")
                        or row.get("updatetime")
                    ),
                )
            await asyncio.sleep(self.poll_interval_seconds)

    def register_recovered_order(self, broker_order_id: str, order: OrderRequest) -> bool:
        broker_order_id = broker_order_id.strip()
        if not broker_order_id:
            raise ValueError("Angel One broker order id is required")
        existing = self._orders_by_broker_id.get(broker_order_id)
        if existing is not None and existing != order:
            raise RuntimeError(f"Angel One order mapping conflict: {broker_order_id}")
        if existing is not None:
            return False
        self._orders_by_broker_id[broker_order_id] = order
        return True

    def _native_symbol(self, row: Mapping[str, Any]) -> str:
        exchange = str(row.get("exchange", row.get("exch_seg", ""))).strip().upper()
        trading_symbol = str(
            row.get("tradingsymbol", row.get("tradingsymbolname", ""))
        ).strip()
        mapped = self._symbol_by_native_route.get((exchange, trading_symbol))
        if mapped is not None:
            return mapped
        return f"external-angel-one:{exchange or 'UNKNOWN'}:{trading_symbol or 'UNKNOWN'}"

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Angel One adapter is not connected")


def _response_data(response: Any, context: str) -> Any:
    if not isinstance(response, dict):
        raise TypeError(f"{context} response must be a JSON object")
    if response.get("status") is not True:
        code = str(response.get("errorcode", "")).strip()
        message = str(response.get("message", "request failed")).strip()
        suffix = f" ({code})" if code else ""
        raise RuntimeError(f"{context} failed: {message}{suffix}")
    if "data" not in response:
        raise RuntimeError(f"{context} response is missing data")
    return response["data"]


def _response_rows(response: Any, context: str) -> list[dict[str, Any]]:
    data = _response_data(response, context)
    if data is None:
        return []
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise RuntimeError(f"{context} data must be a list of objects")
    return data


def _integer_quantity(quantity: Decimal) -> int:
    if quantity != quantity.to_integral_value():
        raise ValueError("Angel One order quantity must be an integer number of units")
    return int(quantity)


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return "0"
    return format(value, "f")


def _order_fields(order: OrderRequest) -> tuple[str, str, str]:
    if order.order_type == OrderType.MARKET:
        return "MARKET", "0", "0"
    if order.order_type == OrderType.LIMIT:
        return "LIMIT", _decimal_text(order.limit_price), "0"
    if order.order_type == OrderType.STOP:
        return "STOPLOSS_MARKET", "0", _decimal_text(order.stop_price)
    raise ValueError(f"unsupported Angel One order type: {order.order_type}")


def _order_tag(value: str) -> str:
    sanitized = "".join(character for character in value if character.isalnum() or character in "_-")
    return (sanitized or "aura")[:19]


def _order_status(raw: Any) -> OrderStatus:
    value = str(raw or "").strip().upper().replace(" ", "_")
    mapping = {
        "OPEN": OrderStatus.SUBMITTED,
        "PENDING": OrderStatus.SUBMITTED,
        "TRIGGER_PENDING": OrderStatus.SUBMITTED,
        "VALIDATION_PENDING": OrderStatus.SUBMITTED,
        "AFTER_MARKET_ORDER_REQ_RECEIVED": OrderStatus.SUBMITTED,
        "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
        "PARTIAL": OrderStatus.PARTIALLY_FILLED,
        "COMPLETE": OrderStatus.FILLED,
        "FILLED": OrderStatus.FILLED,
        "CANCELLED": OrderStatus.CANCELLED,
        "CANCELED": OrderStatus.CANCELLED,
        "REJECTED": OrderStatus.REJECTED,
        "EXPIRED": OrderStatus.EXPIRED,
    }
    if value not in mapping:
        raise RuntimeError(f"unknown Angel One order status: {raw!r}")
    return mapping[value]


def _timestamp(raw: Any) -> datetime:
    if raw is None or not str(raw).strip():
        raise RuntimeError("Angel One trade timestamp is missing")
    value = str(raw).strip()
    for pattern in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        except ValueError:
            continue
    raise RuntimeError(f"unsupported Angel One timestamp: {value}")
