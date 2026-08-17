from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.core.pipeline import DecisionPipeline, DecisionResult
from aura.domain.models import Fill, NormalizedCandle, OrderRequest, Side
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
    equity_curve: tuple[Decimal, ...] = ()
    period_returns: tuple[Decimal, ...] = ()


class BacktestEngine:
    """Event-driven single-series backtester using the shared DecisionPipeline.

    Signals are computed after a candle is closed. Approved market orders are
    filled at the next candle's open, avoiding same-close lookahead execution.
    `signal_start_index` lets research evaluators prepend causal warm-up history
    without permitting trades in the warm-up section.
    """

    def __init__(
        self,
        pipeline: DecisionPipeline,
        starting_cash: Decimal,
        requested_quantity: Decimal,
        fee_bps: Decimal = Decimal(0),
        slippage_bps: Decimal = Decimal(0),
    ) -> None:
        if requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive")
        if fee_bps < 0 or slippage_bps < 0:
            raise ValueError("fee/slippage bps cannot be negative")
        self.pipeline = pipeline
        self.ledger = PortfolioLedger(starting_cash)
        self.requested_quantity = requested_quantity
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def run(
        self,
        candles: list[NormalizedCandle],
        *,
        signal_start_index: int = 0,
    ) -> BacktestResult:
        if not candles:
            raise ValueError("candles cannot be empty")
        if any(not candle.closed for candle in candles):
            raise ValueError("backtest accepts only closed candles")
        if len({candle.symbol for candle in candles}) != 1:
            raise ValueError("BacktestEngine accepts one symbol; use a portfolio event runner")
        if not 0 <= signal_start_index < len(candles):
            raise ValueError("signal_start_index must identify a candle in the series")

        history: list[NormalizedCandle] = []
        pending: OrderRequest | None = None
        orders = 0
        fills = 0
        rejected = 0
        max_drawdown = Decimal(0)
        day_start_equity = self.ledger.starting_cash
        last_date = candles[0].open_time.date()
        equity_curve: list[Decimal] = [self.ledger.starting_cash]
        period_returns: list[Decimal] = []

        for index, candle in enumerate(candles):
            if candle.open_time.date() != last_date:
                marks = {candle.symbol: candle.open}
                day_start_equity = self.ledger.snapshot(marks).equity
                last_date = candle.open_time.date()

            if pending is not None:
                state = OrderState(pending)
                state.submit()
                fill_price = self._apply_slippage(candle.open, pending.side)
                notional = pending.quantity * fill_price
                fee = notional * self.fee_bps / Decimal(10000)
                fill = Fill(
                    fill_id=f"bt:{pending.order_id}:{candle.open_time.isoformat()}",
                    order_id=pending.order_id,
                    symbol=pending.symbol,
                    side=pending.side,
                    quantity=pending.quantity,
                    price=fill_price,
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
            previous_equity = equity_curve[-1]
            equity_curve.append(snapshot.equity)
            period_returns.append(
                snapshot.equity / previous_equity - Decimal(1)
                if previous_equity > 0
                else Decimal(0)
            )

            if index < signal_start_index:
                continue

            position = self.ledger.positions.get(candle.symbol)
            current_position_quantity = position.quantity if position is not None else Decimal(0)
            result: DecisionResult | None = self.pipeline.evaluate_closed_candle(
                history=history,
                portfolio=snapshot,
                day_start_equity=day_start_equity,
                venue=candle.venue,
                requested_quantity=self.requested_quantity,
                current_position_quantity=current_position_quantity,
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
            equity_curve=tuple(equity_curve),
            period_returns=tuple(period_returns),
        )

    def _apply_slippage(self, price: Decimal, side: Side) -> Decimal:
        slippage = self.slippage_bps / Decimal(10000)
        multiplier = Decimal(1) + slippage if side == Side.BUY else Decimal(1) - slippage
        return price * multiplier
