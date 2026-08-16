from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.core.pipeline import DecisionPipeline, DecisionResult
from aura.domain.models import Fill, NormalizedCandle, OrderRequest
from aura.execution.state import OrderState
from aura.portfolio.ledger import PortfolioLedger


@dataclass(slots=True, frozen=True)
class BacktestResult:
    starting_equity: Decimal
    ending_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    max_drawdown_pct: Decimal
    orders: int
    fills: int
    rejected_signals: int


class BacktestEngine:
    """Event-driven backtester that reuses the exact DecisionPipeline.

    Signals are computed after a candle is closed. Approved market orders are
    filled at the next candle's open, avoiding same-close lookahead execution.
    """

    def __init__(
        self,
        pipeline: DecisionPipeline,
        starting_cash: Decimal,
        requested_quantity: Decimal,
        fee_bps: Decimal = Decimal("0"),
    ) -> None:
        if requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive")
        if fee_bps < 0:
            raise ValueError("fee_bps cannot be negative")
        self.pipeline = pipeline
        self.ledger = PortfolioLedger(starting_cash)
        self.requested_quantity = requested_quantity
        self.fee_bps = fee_bps

    def run(self, candles: list[NormalizedCandle]) -> BacktestResult:
        if not candles:
            raise ValueError("candles cannot be empty")
        if any(not candle.closed for candle in candles):
            raise ValueError("backtest accepts only closed candles")

        history: list[NormalizedCandle] = []
        pending: OrderRequest | None = None
        orders = 0
        fills = 0
        rejected = 0
        max_drawdown = Decimal("0")
        day_start_equity = self.ledger.starting_cash
        last_date = candles[0].open_time.date()

        for candle in candles:
            if candle.open_time.date() != last_date:
                marks = {candle.symbol: candle.open}
                day_start_equity = self.ledger.snapshot(marks).equity
                last_date = candle.open_time.date()

            if pending is not None:
                state = OrderState(pending)
                state.submit()
                notional = pending.quantity * candle.open
                fee = notional * self.fee_bps / Decimal("10000")
                fill = Fill(
                    fill_id=f"bt:{pending.order_id}:{candle.open_time.isoformat()}",
                    order_id=pending.order_id,
                    symbol=pending.symbol,
                    side=pending.side,
                    quantity=pending.quantity,
                    price=candle.open,
                    fee=fee,
                    timestamp=candle.open_time,
                )
                state.apply_fill(fill)
                self.ledger.apply_fill(fill)
                fills += 1
                pending = None

            history.append(candle)
            marks = {candle.symbol: candle.close}
            snapshot = self.ledger.snapshot(marks)
            max_drawdown = max(max_drawdown, snapshot.drawdown_pct)

            result: DecisionResult | None = self.pipeline.evaluate_closed_candle(
                history=history,
                portfolio=snapshot,
                day_start_equity=day_start_equity,
                venue=candle.venue,
                requested_quantity=self.requested_quantity,
            )
            if result is None:
                continue
            if result.order is None:
                rejected += 1
                continue
            pending = result.order
            orders += 1

        final_marks = {candles[-1].symbol: candles[-1].close}
        final_snapshot = self.ledger.snapshot(final_marks)
        max_drawdown = max(max_drawdown, final_snapshot.drawdown_pct)
        return BacktestResult(
            starting_equity=self.ledger.starting_cash,
            ending_equity=final_snapshot.equity,
            realized_pnl=final_snapshot.realized_pnl,
            unrealized_pnl=final_snapshot.unrealized_pnl,
            max_drawdown_pct=max_drawdown,
            orders=orders,
            fills=fills,
            rejected_signals=rejected,
        )
