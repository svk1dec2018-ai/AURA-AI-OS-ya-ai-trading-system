from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.core.pipeline import DecisionPipeline, DecisionResult
from aura.domain.models import Fill, NormalizedCandle, OrderRequest
from aura.execution.fill_model import CandleExecutionModel, ExecutionCostModel
from aura.execution.state import OrderState
from aura.portfolio.instruments import InstrumentLedgerSpec
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
    fill_records: tuple[Fill, ...] = ()


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
        instrument_specs: dict[str, InstrumentLedgerSpec] | None = None,
    ) -> None:
        if requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive")
        if fee_bps < 0 or slippage_bps < 0:
            raise ValueError("fee/slippage bps cannot be negative")
        self.pipeline = pipeline
        self.ledger = PortfolioLedger(starting_cash, instrument_specs=instrument_specs)
        self.requested_quantity = requested_quantity
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.execution_model = CandleExecutionModel(
            ExecutionCostModel(fee_bps=fee_bps, slippage_bps=slippage_bps)
        )

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
        _validate_causal_series(candles)
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
        position_entry_index: int | None = None
        fill_records: list[Fill] = []

        for index, candle in enumerate(candles):
            pending_unfilled = False
            if candle.open_time.date() != last_date:
                marks = {candle.symbol: candle.open}
                day_start_equity = self.ledger.snapshot(marks).equity
                last_date = candle.open_time.date()

            if pending is not None:
                prior_position = self.ledger.positions.get(pending.symbol)
                old_qty = (
                    prior_position.quantity if prior_position is not None else Decimal(0)
                )
                state = OrderState(pending)
                state.submit()
                spec = self.ledger.instrument_spec(pending.symbol)
                quote = self.execution_model.quote(
                    pending,
                    candle,
                    contract_multiplier=spec.contract_multiplier,
                )
                if quote is None:
                    pending_unfilled = True
                else:
                    fill = Fill(
                        fill_id=f"bt:{pending.order_id}:{candle.open_time.isoformat()}",
                        order_id=pending.order_id,
                        symbol=pending.symbol,
                        side=pending.side,
                        quantity=quote.quantity,
                        price=quote.price,
                        fee=quote.fee,
                        timestamp=candle.open_time,
                    )
                    state.apply_fill(fill)
                    self.ledger.apply_fill(fill)
                    fill_records.append(fill)
                    position = self.ledger.positions.get(pending.symbol)
                    new_qty = position.quantity if position is not None else Decimal(0)
                    if new_qty == 0:
                        position_entry_index = None
                    elif old_qty == 0 or (old_qty > 0 > new_qty) or (old_qty < 0 < new_qty):
                        position_entry_index = index
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

            if pending_unfilled or index < signal_start_index:
                continue

            position = self.ledger.positions.get(candle.symbol)
            current_position_quantity = (
                position.quantity if position is not None else Decimal(0)
            )
            position_average_price = (
                position.average_price if position is not None else Decimal(0)
            )
            bars_in_position = (
                index - position_entry_index + 1
                if current_position_quantity != 0 and position_entry_index is not None
                else 0
            )
            result: DecisionResult | None = self.pipeline.evaluate_closed_candle(
                history=history,
                portfolio=snapshot,
                day_start_equity=day_start_equity,
                venue=candle.venue,
                requested_quantity=self.requested_quantity,
                current_position_quantity=current_position_quantity,
                position_average_price=position_average_price,
                bars_in_position=bars_in_position,
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
            fill_records=tuple(fill_records),
        )


def _validate_causal_series(candles: list[NormalizedCandle]) -> None:
    if len({candle.venue for candle in candles}) != 1:
        raise ValueError("backtest series must use one venue")
    if len({candle.timeframe for candle in candles}) != 1:
        raise ValueError("backtest series must use one timeframe")
    previous: NormalizedCandle | None = None
    for candle in candles:
        if previous is not None:
            if candle.open_time <= previous.open_time or candle.close_time <= previous.close_time:
                raise ValueError("backtest series must be strictly increasing")
            if candle.open_time < previous.close_time:
                raise ValueError("backtest candles cannot overlap")
        previous = candle
