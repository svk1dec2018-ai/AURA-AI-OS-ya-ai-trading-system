from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.domain.models import NormalizedCandle, OrderRequest, OrderType, Side


@dataclass(slots=True, frozen=True)
class ExecutionCostModel:
    """Deterministic cost assumptions shared by backtest and paper execution."""

    fee_bps: Decimal = Decimal(0)
    slippage_bps: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("execution fees/slippage cannot be negative")


@dataclass(slots=True, frozen=True)
class CandleFillQuote:
    price: Decimal
    quantity: Decimal
    fee: Decimal


class CandleExecutionModel:
    """One causal candle-fill model for research backtests and paper runtime.

    The model never sees a candle until the caller's event loop releases it.
    Market orders use that candle's open. Limit/stop orders use deterministic
    gap-aware rules and all fills receive adverse-side slippage plus explicit
    contract-aware fees.
    """

    def __init__(self, costs: ExecutionCostModel | None = None) -> None:
        self.costs = costs or ExecutionCostModel()

    def quote(
        self,
        order: OrderRequest,
        candle: NormalizedCandle,
        *,
        quantity: Decimal | None = None,
        contract_multiplier: Decimal = Decimal(1),
    ) -> CandleFillQuote | None:
        if not candle.closed:
            raise ValueError("execution model accepts only closed candles")
        if candle.symbol != order.symbol:
            raise ValueError("order and candle symbols must match")
        fill_quantity = order.quantity if quantity is None else quantity
        if fill_quantity <= 0:
            raise ValueError("fill quantity must be positive")
        if fill_quantity > order.quantity:
            raise ValueError("fill quantity cannot exceed order quantity")
        if contract_multiplier <= 0:
            raise ValueError("contract multiplier must be positive")

        raw_price = self._eligible_price(order, candle)
        if raw_price is None:
            return None
        price = self._apply_adverse_slippage(raw_price, order.side)
        notional = fill_quantity * price * contract_multiplier
        fee = notional * self.costs.fee_bps / Decimal(10000)
        return CandleFillQuote(price=price, quantity=fill_quantity, fee=fee)

    def _eligible_price(
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
        raise ValueError(f"unsupported order type: {order.order_type}")

    def _apply_adverse_slippage(self, price: Decimal, side: Side) -> Decimal:
        slippage = self.costs.slippage_bps / Decimal(10000)
        multiplier = Decimal(1) + slippage if side == Side.BUY else Decimal(1) - slippage
        return price * multiplier
