from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.backtest.scheduler import MultiSymbolEventScheduler
from aura.core.pipeline import DecisionPipeline
from aura.domain.models import Fill, NormalizedCandle, OrderRequest, SignalIntent, StrategySignal
from aura.execution.state import OrderState
from aura.portfolio.ledger import PortfolioLedger


@dataclass(slots=True, frozen=True)
class MultiSymbolBacktestResult:
    starting_equity: Decimal
    ending_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    max_drawdown_pct: Decimal
    orders: int
    fills: int
    rejected_signals: int
    symbols: tuple[str, ...]


class MultiSymbolBacktestEngine:
    """Causal multi-symbol backtester with one shared portfolio/risk budget.

    All candles closing at the same timestamp are added to their histories before
    candidate signals are ranked. Approved-but-unfilled market orders reserve
    gross exposure before lower-ranked candidates are evaluated, preventing
    historical capital from being allocated multiple times in the same batch.
    """

    def __init__(
        self,
        *,
        pipelines: dict[str, DecisionPipeline],
        starting_cash: Decimal,
        requested_quantities: dict[str, Decimal],
        fee_bps: Decimal = Decimal(0),
    ) -> None:
        if not pipelines:
            raise ValueError("multi-symbol backtest requires at least one pipeline")
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        if fee_bps < 0:
            raise ValueError("fee_bps cannot be negative")
        if set(pipelines) != set(requested_quantities):
            raise ValueError("pipelines and requested_quantities must have identical symbols")
        if any(quantity <= 0 for quantity in requested_quantities.values()):
            raise ValueError("all requested quantities must be positive")
        self.pipelines = dict(pipelines)
        self.requested_quantities = dict(requested_quantities)
        self.ledger = PortfolioLedger(starting_cash)
        self.fee_bps = fee_bps

    def run(
        self,
        series: dict[str, list[NormalizedCandle] | tuple[NormalizedCandle, ...]],
    ) -> MultiSymbolBacktestResult:
        if set(series) != set(self.pipelines):
            raise ValueError("series symbols must exactly match configured pipelines")

        batches = MultiSymbolEventScheduler().build(series)
        histories: dict[str, list[NormalizedCandle]] = {symbol: [] for symbol in series}
        pending: dict[str, OrderRequest] = {}
        marks: dict[str, Decimal] = {}
        orders = 0
        fills = 0
        rejected = 0
        max_drawdown = Decimal(0)
        day_start_equity = self.ledger.starting_cash
        current_date = batches[0].close_time.date()
        previous_batch_equity = self.ledger.starting_cash

        for batch in batches:
            batch_date = batch.close_time.date()
            if batch_date != current_date:
                day_start_equity = previous_batch_equity
                current_date = batch_date

            for candle in batch.candles:
                order = pending.pop(candle.symbol, None)
                if order is None:
                    continue
                state = OrderState(order)
                state.submit()
                notional = order.quantity * candle.open
                fee = notional * self.fee_bps / Decimal(10000)
                fill = Fill(
                    fill_id=f"multi-bt:{order.order_id}:{candle.open_time.isoformat()}",
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    price=candle.open,
                    fee=fee,
                    timestamp=candle.open_time,
                )
                state.apply_fill(fill)
                self.ledger.apply_fill(fill)
                fills += 1

            for candle in batch.candles:
                histories[candle.symbol].append(candle)
                marks[candle.symbol] = candle.close

            portfolio = self.ledger.snapshot(marks)
            max_drawdown = max(max_drawdown, portfolio.drawdown_pct)
            candidates: list[tuple[str, StrategySignal]] = []
            for candle in batch.candles:
                pipeline = self.pipelines[candle.symbol]
                signal = pipeline.strategy.on_closed_candle(histories[candle.symbol])
                if signal is None or signal.intent == SignalIntent.FLAT:
                    continue
                candidates.append((candle.symbol, signal))

            candidates.sort(key=lambda item: (-item[1].confidence, item[0]))
            reserved_gross = Decimal(0)
            for symbol, signal in candidates:
                pipeline = self.pipelines[symbol]
                effective_portfolio = portfolio.model_copy(
                    update={"gross_exposure": portfolio.gross_exposure + reserved_gross}
                )
                position = self.ledger.positions.get(symbol)
                current_quantity = position.quantity if position is not None else Decimal(0)
                decision = pipeline.evaluate_signal(
                    signal=signal,
                    portfolio=effective_portfolio,
                    day_start_equity=day_start_equity,
                    venue=histories[symbol][-1].venue,
                    requested_quantity=self.requested_quantities[symbol],
                    current_position_quantity=current_quantity,
                )
                if decision is None:
                    continue
                if decision.order is None:
                    rejected += 1
                    continue
                pending[symbol] = decision.order
                reserved_gross += decision.order.quantity * signal.reference_price
                orders += 1

            previous_batch_equity = portfolio.equity

        final_snapshot = self.ledger.snapshot(marks)
        max_drawdown = max(max_drawdown, final_snapshot.drawdown_pct)
        return MultiSymbolBacktestResult(
            starting_equity=self.ledger.starting_cash,
            ending_equity=final_snapshot.equity,
            realized_pnl=final_snapshot.realized_pnl,
            unrealized_pnl=final_snapshot.unrealized_pnl,
            max_drawdown_pct=max_drawdown,
            orders=orders,
            fills=fills,
            rejected_signals=rejected,
            symbols=tuple(sorted(series)),
        )
