from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from aura.data.mt5_demo import OfficialMT5Gateway
from aura.domain.models import Fill, OrderRequest, OrderStatus, OrderType, Side
from aura.execution.broker import BrokerAdapter, BrokerCapabilities, BrokerExecutionMode
from aura.execution.demo_guard import DemoExecutionGuard
from aura.execution.reconciliation import BrokerOrderSnapshot, BrokerPositionSnapshot


@dataclass(slots=True, frozen=True)
class MT5DemoBrokerConfig:
    magic: int = 560026
    deviation_points: int = 20
    fill_poll_seconds: float = 1.0
    history_lookback_seconds: int = 15
    comment_prefix: str = "AURA"

    def __post_init__(self) -> None:
        if self.magic <= 0:
            raise ValueError("MT5 magic must be positive")
        if self.deviation_points < 0:
            raise ValueError("MT5 deviation_points cannot be negative")
        if self.fill_poll_seconds <= 0 or self.history_lookback_seconds <= 0:
            raise ValueError("MT5 fill polling configuration must be positive")
        if not self.comment_prefix or len(self.comment_prefix) > 10:
            raise ValueError("MT5 comment_prefix must contain 1-10 characters")


class MT5DemoBroker(BrokerAdapter):
    """Market-order BrokerAdapter for a verified MetaTrader 5 DEMO account."""

    name = "MT5_DEMO"
    capabilities = BrokerCapabilities(
        mode=BrokerExecutionMode.DEMO,
        supports_order_submission=True,
        supports_order_cancellation=True,
        supports_fill_stream=True,
        supports_reconciliation=True,
    )

    def __init__(
        self,
        gateway: OfficialMT5Gateway,
        *,
        config: MT5DemoBrokerConfig | None = None,
    ) -> None:
        if not gateway.demo_verified:
            raise RuntimeError("MT5DemoBroker requires a verified DEMO gateway")
        self.gateway = gateway
        self.config = config or MT5DemoBrokerConfig()
        self._connected = False
        self._order_by_ticket: dict[int, OrderRequest] = {}
        self._order_by_token: dict[str, OrderRequest] = {}
        self._seen_deals: set[int] = set()
        self._history_cursor = datetime.now(UTC) - timedelta(
            seconds=self.config.history_lookback_seconds
        )

    async def connect(self) -> None:
        info = await asyncio.to_thread(self.gateway.account_info)
        if info is None:
            raise RuntimeError(f"MT5 account_info failed: {self.gateway.last_error()}")
        DemoExecutionGuard.assert_mt5_demo_account(info)
        self._connected = True
        self._history_cursor = datetime.now(UTC) - timedelta(
            seconds=self.config.history_lookback_seconds
        )

    async def disconnect(self) -> None:
        self._connected = False

    async def submit_order(self, order: OrderRequest) -> str:
        self._require_connected()
        if order.order_type != OrderType.MARKET:
            raise ValueError("MT5 demo adapter currently permits market orders only")
        return str(await asyncio.to_thread(self._submit_market_sync, order))

    async def cancel_order(self, broker_order_id: str) -> None:
        self._require_connected()
        try:
            ticket = int(broker_order_id)
        except ValueError as exc:
            raise ValueError("MT5 broker_order_id must be a numeric ticket") from exc
        await asyncio.to_thread(self._cancel_sync, ticket)

    async def fills(self):
        while self._connected:
            for fill in await asyncio.to_thread(self._poll_fills_sync):
                yield fill
            await asyncio.sleep(self.config.fill_poll_seconds)

    def open_order_snapshots(self) -> list[BrokerOrderSnapshot]:
        rows = self.gateway.orders_get()
        if rows is None:
            raise RuntimeError(f"MT5 orders_get failed: {self.gateway.last_error()}")
        snapshots: list[BrokerOrderSnapshot] = []
        for row in rows:
            source = _asdict(row)
            ticket = int(source.get("ticket", 0))
            mapped = self._order_by_ticket.get(ticket)
            if mapped is None:
                client_order_id = f"external-mt5:{ticket}"
                symbol = str(source.get("symbol", ""))
                side = self._side_from_order_type(int(source.get("type", -1)))
                initial = Decimal(str(source.get("volume_initial", 0)))
            else:
                client_order_id = mapped.client_order_id
                symbol = mapped.symbol
                side = mapped.side
                initial = mapped.quantity
            if initial <= 0:
                continue
            remaining = Decimal(str(source.get("volume_current", initial)))
            filled = max(Decimal(0), initial - remaining)
            snapshots.append(
                BrokerOrderSnapshot(
                    broker_order_id=str(ticket),
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side,
                    quantity=initial,
                    filled_quantity=filled,
                    status=(
                        OrderStatus.PARTIALLY_FILLED
                        if filled > 0
                        else OrderStatus.SUBMITTED
                    ),
                )
            )
        return snapshots

    def position_snapshots(self) -> list[BrokerPositionSnapshot]:
        rows = self.gateway.positions_get()
        if rows is None:
            raise RuntimeError(f"MT5 positions_get failed: {self.gateway.last_error()}")
        quantities: dict[str, Decimal] = {}
        for row in rows:
            source = _asdict(row)
            symbol = str(source.get("symbol", ""))
            volume = Decimal(str(source.get("volume", 0)))
            if not symbol or volume <= 0:
                continue
            position_type = int(source.get("type", -1))
            if position_type == self.gateway.constant("POSITION_TYPE_BUY"):
                signed = volume
            elif position_type == self.gateway.constant("POSITION_TYPE_SELL"):
                signed = -volume
            else:
                raise RuntimeError(f"unknown MT5 position type: {position_type}")
            quantities[symbol] = quantities.get(symbol, Decimal(0)) + signed
        return [
            BrokerPositionSnapshot(symbol=symbol, quantity=quantity)
            for symbol, quantity in sorted(quantities.items())
            if quantity != 0
        ]

    async def margin_required(self, order: OrderRequest) -> Decimal:
        self._require_connected()
        tick = await asyncio.to_thread(self.gateway.symbol_info_tick, order.symbol)
        if tick is None:
            raise RuntimeError(f"missing MT5 tick: {order.symbol}")
        tick_data = _asdict(tick)
        price = Decimal(
            str(tick_data["ask"] if order.side == Side.BUY else tick_data["bid"])
        )
        margin = await asyncio.to_thread(
            self.gateway.order_calc_margin,
            self._mt5_market_type(order.side),
            order.symbol,
            float(order.quantity),
            float(price),
        )
        if margin is None:
            raise RuntimeError(f"MT5 order_calc_margin failed: {self.gateway.last_error()}")
        return Decimal(str(margin))

    def _submit_market_sync(self, order: OrderRequest) -> int:
        info = self.gateway.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info failed: {self.gateway.last_error()}")
        DemoExecutionGuard.assert_mt5_demo_account(info)
        raw_symbol = self.gateway.symbol_info(order.symbol)
        if raw_symbol is None:
            raise RuntimeError(f"MT5 symbol_info failed for {order.symbol}")
        symbol = _asdict(raw_symbol)
        if not bool(symbol.get("visible", True)) and not self.gateway.symbol_select(order.symbol, True):
            raise RuntimeError(f"MT5 could not select {order.symbol} in MarketWatch")
        self._validate_volume(order.quantity, symbol)

        tick = self.gateway.symbol_info_tick(order.symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick failed for {order.symbol}")
        tick_data = _asdict(tick)
        price = Decimal(str(tick_data["ask"] if order.side == Side.BUY else tick_data["bid"]))
        if price <= 0:
            raise RuntimeError(f"MT5 returned non-positive tradable price for {order.symbol}")

        token = hashlib.sha1(order.client_order_id.encode("utf-8")).hexdigest()[:12]
        request: dict[str, Any] = {
            "action": self.gateway.constant("TRADE_ACTION_DEAL"),
            "symbol": order.symbol,
            "volume": float(order.quantity),
            "type": self._mt5_market_type(order.side),
            "deviation": self.config.deviation_points,
            "magic": self.config.magic,
            "comment": f"{self.config.comment_prefix}:{token}",
            "type_time": self.gateway.constant("ORDER_TIME_GTC"),
            "type_filling": self._resolve_filling(symbol),
        }
        if int(symbol.get("trade_exemode", -1)) != self.gateway.constant(
            "SYMBOL_TRADE_EXECUTION_MARKET"
        ):
            request["price"] = float(price)

        check = self.gateway.order_check(request)
        if check is None:
            raise RuntimeError(f"MT5 order_check returned None: {self.gateway.last_error()}")
        check_data = _asdict(check)
        if int(check_data.get("retcode", -1)) != 0:
            raise RuntimeError(
                f"MT5 order_check rejected {order.symbol}: "
                f"retcode={check_data.get('retcode')} comment={check_data.get('comment', '')}"
            )

        result = self.gateway.order_send(request)
        if result is None:
            raise RuntimeError(f"MT5 order_send returned None: {self.gateway.last_error()}")
        result_data = _asdict(result)
        accepted = {
            self.gateway.constant("TRADE_RETCODE_DONE"),
            self.gateway.constant("TRADE_RETCODE_DONE_PARTIAL"),
            self.gateway.constant("TRADE_RETCODE_PLACED"),
        }
        retcode = int(result_data.get("retcode", -1))
        if retcode not in accepted:
            raise RuntimeError(
                f"MT5 order_send rejected {order.symbol}: "
                f"retcode={retcode} comment={result_data.get('comment', '')}"
            )
        ticket = int(result_data.get("order", 0))
        if ticket <= 0:
            raise RuntimeError("MT5 accepted request without returning an order ticket")
        self._order_by_ticket[ticket] = order
        self._order_by_token[token] = order
        return ticket

    def _poll_fills_sync(self) -> tuple[Fill, ...]:
        now = datetime.now(UTC)
        rows = self.gateway.history_deals_get(
            self._history_cursor - timedelta(seconds=1),
            now,
        )
        if rows is None:
            raise RuntimeError(f"MT5 history_deals_get failed: {self.gateway.last_error()}")
        fills: list[Fill] = []
        for row in rows:
            source = _asdict(row)
            deal_ticket = int(source.get("ticket", 0))
            if deal_ticket <= 0 or deal_ticket in self._seen_deals:
                continue
            side = self._side_from_deal_type(int(source.get("type", -1)))
            if side is None:
                continue
            order = self._order_by_ticket.get(int(source.get("order", 0)))
            if order is None:
                token = _token_from_comment(
                    str(source.get("comment", "")),
                    self.config.comment_prefix,
                )
                order = self._order_by_token.get(token) if token else None
            if order is None:
                continue
            volume = Decimal(str(source.get("volume", 0)))
            price = Decimal(str(source.get("price", 0)))
            if volume <= 0 or price <= 0:
                continue
            commission = abs(Decimal(str(source.get("commission", 0))))
            fee = abs(Decimal(str(source.get("fee", 0))))
            fills.append(
                Fill(
                    fill_id=f"mt5-deal:{deal_ticket}",
                    order_id=order.order_id,
                    symbol=str(source.get("symbol", order.symbol)),
                    side=side,
                    quantity=volume,
                    price=price,
                    fee=commission + fee,
                    timestamp=_deal_timestamp(source),
                )
            )
            self._seen_deals.add(deal_ticket)
        self._history_cursor = now
        fills.sort(key=lambda item: (item.timestamp, item.fill_id))
        return tuple(fills)

    def _cancel_sync(self, ticket: int) -> None:
        result = self.gateway.order_send(
            {
                "action": self.gateway.constant("TRADE_ACTION_REMOVE"),
                "order": ticket,
                "magic": self.config.magic,
                "comment": f"{self.config.comment_prefix}:cancel",
            }
        )
        if result is None:
            raise RuntimeError(f"MT5 cancel returned None: {self.gateway.last_error()}")
        data = _asdict(result)
        if int(data.get("retcode", -1)) != self.gateway.constant("TRADE_RETCODE_DONE"):
            raise RuntimeError(
                f"MT5 cancel failed: retcode={data.get('retcode')} "
                f"comment={data.get('comment', '')}"
            )

    def _resolve_filling(self, symbol: dict[str, Any]) -> int:
        mode = int(symbol.get("filling_mode", 0))
        if mode & self.gateway.constant("SYMBOL_FILLING_IOC"):
            return self.gateway.constant("ORDER_FILLING_IOC")
        if mode & self.gateway.constant("SYMBOL_FILLING_FOK"):
            return self.gateway.constant("ORDER_FILLING_FOK")
        if int(symbol.get("trade_exemode", -1)) != self.gateway.constant(
            "SYMBOL_TRADE_EXECUTION_MARKET"
        ):
            return self.gateway.constant("ORDER_FILLING_RETURN")
        raise RuntimeError("MT5 symbol exposes no safe supported filling policy")

    def _mt5_market_type(self, side: Side) -> int:
        return self.gateway.constant("ORDER_TYPE_BUY" if side == Side.BUY else "ORDER_TYPE_SELL")

    def _side_from_order_type(self, order_type: int) -> Side:
        buy_types = {
            self.gateway.constant("ORDER_TYPE_BUY"),
            self.gateway.constant("ORDER_TYPE_BUY_LIMIT"),
            self.gateway.constant("ORDER_TYPE_BUY_STOP"),
            self.gateway.constant("ORDER_TYPE_BUY_STOP_LIMIT"),
        }
        sell_types = {
            self.gateway.constant("ORDER_TYPE_SELL"),
            self.gateway.constant("ORDER_TYPE_SELL_LIMIT"),
            self.gateway.constant("ORDER_TYPE_SELL_STOP"),
            self.gateway.constant("ORDER_TYPE_SELL_STOP_LIMIT"),
        }
        if order_type in buy_types:
            return Side.BUY
        if order_type in sell_types:
            return Side.SELL
        raise RuntimeError(f"unknown MT5 order type: {order_type}")

    def _side_from_deal_type(self, deal_type: int) -> Side | None:
        if deal_type == self.gateway.constant("DEAL_TYPE_BUY"):
            return Side.BUY
        if deal_type == self.gateway.constant("DEAL_TYPE_SELL"):
            return Side.SELL
        return None

    @staticmethod
    def _validate_volume(quantity: Decimal, symbol: dict[str, Any]) -> None:
        minimum = Decimal(str(symbol.get("volume_min", 0)))
        maximum = Decimal(str(symbol.get("volume_max", 0)))
        step = Decimal(str(symbol.get("volume_step", 0)))
        if minimum <= 0 or maximum <= 0 or step <= 0:
            raise RuntimeError("MT5 symbol has invalid volume metadata")
        if not minimum <= quantity <= maximum:
            raise ValueError(f"MT5 volume {quantity} outside [{minimum}, {maximum}]")
        units = (quantity - minimum) / step
        if units != units.to_integral_value():
            raise ValueError(
                f"MT5 volume {quantity} is not aligned to step {step} from minimum {minimum}"
            )

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("MT5 demo broker is not connected")


def _asdict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    return dict(vars(value))


def _token_from_comment(comment: str, prefix: str) -> str | None:
    marker = f"{prefix}:"
    if not comment.startswith(marker):
        return None
    token = comment[len(marker) :].strip()
    return token or None


def _deal_timestamp(source: dict[str, Any]) -> datetime:
    if source.get("time_msc") is not None:
        return datetime.fromtimestamp(int(source["time_msc"]) / 1000, tz=UTC)
    return datetime.fromtimestamp(int(source.get("time", 0)), tz=UTC)
