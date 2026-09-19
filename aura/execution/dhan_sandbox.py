from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from aura.domain.models import Fill, OrderRequest, OrderType, Side, TimeInForce
from aura.execution.broker import BrokerAdapter, BrokerCapabilities, BrokerExecutionMode
from aura.execution.demo_guard import DemoExecutionGuard


@dataclass(slots=True, frozen=True)
class DhanSandboxCredentials:
    client_id: str
    access_token: str


def load_dhan_sandbox_credentials_from_env() -> DhanSandboxCredentials:
    client_id = os.environ.get("AURA_DHAN_SANDBOX_CLIENT_ID", "").strip()
    token = os.environ.get("AURA_DHAN_SANDBOX_ACCESS_TOKEN", "").strip()
    if not client_id or not token:
        raise RuntimeError("set AURA_DHAN_SANDBOX_CLIENT_ID and AURA_DHAN_SANDBOX_ACCESS_TOKEN")
    return DhanSandboxCredentials(client_id=client_id, access_token=token)


@dataclass(slots=True, frozen=True)
class DhanSandboxRoute:
    security_id: str
    exchange_segment: str
    product_type: str = "INTRADAY"


class JsonTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> Any: ...


class UrllibJsonTransport:
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> Any:
        return await asyncio.to_thread(self._sync, method, url, headers, payload)

    @staticmethod
    def _sync(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Dhan sandbox HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Dhan sandbox transport error: {exc.reason}") from exc
        return json.loads(body) if body else {}


class DhanSandboxBroker(BrokerAdapter):
    name = "DHAN_SANDBOX"
    capabilities = BrokerCapabilities(
        mode=BrokerExecutionMode.SANDBOX,
        supports_order_submission=True,
        supports_order_cancellation=True,
        supports_fill_stream=True,
        supports_reconciliation=False,
    )
    base_url = "https://sandbox.dhan.co/v2"

    def __init__(
        self,
        credentials: DhanSandboxCredentials,
        routes: dict[str, DhanSandboxRoute],
        *,
        transport: JsonTransport | None = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        DemoExecutionGuard.assert_dhan_sandbox_url(self.base_url)
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.credentials = credentials
        self.routes = dict(routes)
        self.transport = transport or UrllibJsonTransport()
        self.poll_interval_seconds = poll_interval_seconds
        self._connected = False
        self._orders: dict[str, OrderRequest] = {}
        self._aura_order_by_broker_id: dict[str, str] = {}
        self._seen_trade_ids: set[str] = set()

    async def connect(self) -> None:
        DemoExecutionGuard.assert_dhan_sandbox_url(self.base_url)
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def submit_order(self, order: OrderRequest) -> str:
        self._require_connected()
        route = self.routes.get(order.symbol)
        if route is None:
            raise KeyError(f"missing Dhan sandbox route for {order.symbol}")
        payload = {
            "dhanClientId": self.credentials.client_id,
            "correlationId": _correlation_id(order.client_order_id),
            "transactionType": order.side.value,
            "exchangeSegment": route.exchange_segment,
            "productType": route.product_type,
            "orderType": _dhan_order_type(order),
            "validity": "IOC" if order.time_in_force == TimeInForce.IOC else "DAY",
            "securityId": route.security_id,
            "quantity": _integer_quantity(order.quantity),
            "disclosedQuantity": 0,
            "price": float(order.limit_price or Decimal(0)),
            "triggerPrice": float(order.stop_price or Decimal(0)),
            "afterMarketOrder": False,
            "amoTime": "",
            "boProfitValue": 0,
            "boStopLossValue": 0,
        }
        response = await self._request("POST", "/orders", payload)
        broker_order_id = str(response.get("orderId", "")).strip()
        if not broker_order_id:
            raise RuntimeError(f"Dhan sandbox response missing orderId: {response!r}")
        if str(response.get("orderStatus", "")).upper() == "REJECTED":
            raise RuntimeError(f"Dhan sandbox order rejected: {response!r}")
        self._orders[order.order_id] = order
        self._aura_order_by_broker_id[broker_order_id] = order.order_id
        return broker_order_id

    async def cancel_order(self, broker_order_id: str) -> None:
        self._require_connected()
        if broker_order_id not in self._aura_order_by_broker_id:
            raise KeyError(f"unknown Dhan sandbox order id: {broker_order_id}")
        await self._request("DELETE", f"/orders/{broker_order_id}")

    async def fills(self):
        while self._connected:
            trades = await self._request("GET", "/trades")
            if isinstance(trades, dict):
                trades = [trades]
            for trade in trades or []:
                trade_id = str(trade.get("exchangeTradeId", "")).strip()
                broker_order_id = str(trade.get("orderId", "")).strip()
                if not trade_id or trade_id in self._seen_trade_ids:
                    continue
                aura_order_id = self._aura_order_by_broker_id.get(broker_order_id)
                if aura_order_id is None:
                    continue
                order = self._orders[aura_order_id]
                self._seen_trade_ids.add(trade_id)
                yield Fill(
                    fill_id=f"dhan-sandbox:{trade_id}",
                    order_id=aura_order_id,
                    symbol=order.symbol,
                    side=Side(str(trade["transactionType"]).upper()),
                    quantity=Decimal(str(trade["tradedQuantity"])),
                    price=Decimal(str(trade["tradedPrice"])),
                    fee=Decimal(0),
                    timestamp=_timestamp(trade.get("exchangeTime")),
                )
            await asyncio.sleep(self.poll_interval_seconds)

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        DemoExecutionGuard.assert_dhan_sandbox_url(self.base_url)
        return await self.transport.request(
            method,
            f"{self.base_url}{path}",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "access-token": self.credentials.access_token,
            },
            payload=payload,
        )

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Dhan sandbox broker is not connected")


def _integer_quantity(quantity: Decimal) -> int:
    if quantity != quantity.to_integral_value():
        raise ValueError("Dhan order quantity must be an integer number of units")
    return int(quantity)


def _correlation_id(value: str) -> str:
    normalized = "".join(c for c in value if c.isalnum() or c in "_- ")
    return normalized[:30] or "aura"


def _dhan_order_type(order: OrderRequest) -> str:
    if order.order_type == OrderType.MARKET:
        return "MARKET"
    if order.order_type == OrderType.LIMIT:
        return "LIMIT"
    if order.order_type == OrderType.STOP:
        return "STOP_LOSS_MARKET"
    raise ValueError(f"unsupported Dhan sandbox order type: {order.order_type}")


def _timestamp(raw: Any) -> datetime:
    if not raw:
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    return datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=ZoneInfo("Asia/Kolkata")
    )
