from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from aura.domain.models import Fill, NormalizedCandle, OrderRequest, OrderStatus, OrderType, Side
from aura.execution.broker import BrokerAdapter
from aura.execution.reconciliation import BrokerOrderSnapshot, BrokerPositionSnapshot
from aura.execution.state import OrderState, is_terminal_order_status


@dataclass(slots=True, frozen=True)
class PaperExecutionConfig:
    fee_bps: Decimal = Decimal(0)
    slippage_bps: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("paper execution fees/slippage cannot be negative")


class PaperBroker(BrokerAdapter):
    """Deterministic paper broker using contract-aware fees and adverse slippage."""

    name = "AURA_PAPER"

    def __init__(
        self,
        config: PaperExecutionConfig | None = None,
        *,
        contract_multipliers: dict[str, Decimal] | None = None,
    ) -> None:
        self.config = config or PaperExecutionConfig()
        self.contract_multipliers = dict(contract_multipliers or {})
        if any(value <= 0 for value in self.contract_multipliers.values()):
            raise ValueError("paper broker contract multipliers must be positive")
        self._connected = False
        self._orders: dict[str, OrderState] = {}
        self._broker_ids_by_client_id: dict[str, str] = {}
        self._client_ids_by_broker_id: dict[str, str] = {}
        self._fill_queue: asyncio.Queue[Fill] = asyncio.Queue()
        self._positions: dict[str, Decimal] = {}

    def contract_multiplier(self, symbol: str) -> Decimal:
        return self.contract_multipliers.get(symbol, Decimal(1))

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def submit_order(self, order: OrderRequest) -> str:
        self._require_connected()
        existing = self._broker_ids_by_client_id.get(order.client_order_id)
        if existing is not None:
            state = self._orders[order.client_order_id]
            if state.request != order:
                raise ValueError("client_order_id reused with different order payload")
            return existing

        broker_order_id = f"paper-{uuid4()}"
        state = OrderState(order)
        state.submit()
        self._orders[order.client_order_id] = state
        self._broker_ids_by_client_id[order.client_order_id] = broker_order_id
        self._client_ids_by_broker_id[broker_order_id] = order.client_order_id
        return broker_order_id

    async def cancel_order(self, broker_order_id: str) -> None:
        self._require_connected()
        client_order_id = self._client_ids_by_broker_id.get(broker_order_id)
        if client_order_id is None:
            raise KeyError(f"unknown paper broker order id: {broker_order_id}")
        state = self._orders[client_order_id]
        if state.status in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
            state.cancel()

    async def fills(self):
        while self._connected or not self._fill_queue.empty():
            fill = await self._fill_queue.get()
            yield fill

    async def on_candle(self, candle: NormalizedCandle) -> tuple[Fill, ...]:
        self._require_connected()
        if not candle.closed:
            raise ValueError("paper broker accepts only closed candles")

        produced: list[Fill] = []
        for state in tuple(self._orders.values()):
            if state.request.symbol != candle.symbol:
                continue
            if state.status not in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
                continue
            fill_price = self._eligible_fill_price(state.request, candle)
            if fill_price is None:
                continue
            fill_price = self._apply_slippage(fill_price, state.request.side)
            quantity = state.remaining_quantity
            notional = quantity * fill_price * self.contract_multiplier(state.request.symbol)
            fee = notional * self.config.fee_bps / Decimal(10000)
            fill = Fill(
                fill_id=f"paper-fill-{uuid4()}",
                order_id=state.request.order_id,
                symbol=state.request.symbol,
                side=state.request.side,
                quantity=quantity,
                price=fill_price,
                fee=fee,
                timestamp=candle.open_time,
            )
            state.apply_fill(fill)
            signed = quantity if fill.side == Side.BUY else -quantity
            self._positions[fill.symbol] = self._positions.get(fill.symbol, Decimal(0)) + signed
            await self._fill_queue.put(fill)
            produced.append(fill)
        return tuple(produced)

    def open_order_snapshots(self) -> list[BrokerOrderSnapshot]:
        snapshots: list[BrokerOrderSnapshot] = []
        for client_order_id, state in self._orders.items():
            if is_terminal_order_status(state.status):
                continue
            snapshots.append(
                BrokerOrderSnapshot(
                    broker_order_id=self._broker_ids_by_client_id[client_order_id],
                    client_order_id=client_order_id,
                    symbol=state.request.symbol,
                    side=state.request.side,
                    quantity=state.request.quantity,
                    filled_quantity=state.filled_quantity,
                    status=state.status,
                )
            )
        return snapshots

    def position_snapshots(self) -> list[BrokerPositionSnapshot]:
        return [
            BrokerPositionSnapshot(symbol=symbol, quantity=quantity)
            for symbol, quantity in sorted(self._positions.items())
            if quantity != 0
        ]

    def _eligible_fill_price(
        self,
        order: OrderRequest,
        candle: NormalizedCandle,
    ) -> Decimal | None:
        if order.order_type == OrderType.MARKET:
            return candle.open
        if order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                raise ValueError("limit order missing limit_price")
            if order.side == Side.BUY and candle.low <= order.limit_price:
                return min(candle.open, order.limit_price)
            if order.side == Side.SELL and candle.high >= order.limit_price:
                return max(candle.open, order.limit_price)
            return None
        if order.order_type == OrderType.STOP:
            if order.stop_price is None:
                raise ValueError("stop order missing stop_price")
            if order.side == Side.BUY and candle.high >= order.stop_price:
                return max(candle.open, order.stop_price)
            if order.side == Side.SELL and candle.low <= order.stop_price:
                return min(candle.open, order.stop_price)
            return None
        raise ValueError(f"unsupported paper order type: {order.order_type}")

    def _apply_slippage(self, price: Decimal, side: Side) -> Decimal:
        slippage = self.config.slippage_bps / Decimal(10000)
        multiplier = Decimal(1) + slippage if side == Side.BUY else Decimal(1) - slippage
        return price * multiplier

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("paper broker is not connected")
