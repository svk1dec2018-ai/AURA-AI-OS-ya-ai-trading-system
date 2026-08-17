from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aura.agents.audit import AgentAuditJournal
from aura.agents.models import AgentContext
from aura.domain.models import Fill, NormalizedCandle, OrderRequest, PortfolioSnapshot
from aura.execution.paper import PaperBroker
from aura.execution.reconciliation import (
    ReconciliationEngine,
    ReconciliationReport,
    ReconciliationSupervisor,
)
from aura.persistence.recovery import FinancialEventJournal, recover_financial_state
from aura.portfolio.ledger import PortfolioLedger
from aura.risk.engine import RiskEngine
from aura.runtime.allocation import PortfolioAllocationResult, PortfolioRiskCoordinator
from aura.runtime.scanner import MarketScanResult, MultiMarketIntelligenceScanner

BatchMetadataProvider = Callable[
    [NormalizedCandle, tuple[NormalizedCandle, ...]],
    dict[str, Any],
]


@dataclass(slots=True, frozen=True)
class SubmittedPaperOrder:
    correlation_id: str
    order: OrderRequest
    broker_order_id: str


@dataclass(slots=True, frozen=True)
class MultiMarketPaperStep:
    close_time_iso: str
    fills: tuple[Fill, ...]
    scan: MarketScanResult
    allocation: PortfolioAllocationResult
    submitted_orders: tuple[SubmittedPaperOrder, ...]
    portfolio: PortfolioSnapshot


class MultiMarketPaperCoordinator:
    """Coordinated multi-market paper loop with concurrent intelligence and central risk.

    Market intelligence is parallel; financial allocation is intentionally
    serialized through `PortfolioRiskCoordinator`. Existing broker orders are
    advanced before new decisions, guaranteeing that a signal cannot fill on the
    same candle batch that generated it.
    """

    def __init__(
        self,
        *,
        scanner: MultiMarketIntelligenceScanner,
        allocator: PortfolioRiskCoordinator,
        broker: PaperBroker,
        ledger: PortfolioLedger,
        financial_journal: FinancialEventJournal,
        agent_audit_journal: AgentAuditJournal,
        risk_engine: RiskEngine,
        starting_cash: Decimal,
        default_requested_quantity: Decimal,
        requested_quantities: dict[str, Decimal] | None = None,
        max_history_bars: int = 5000,
        metadata_provider: BatchMetadataProvider | None = None,
    ) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        if default_requested_quantity <= 0:
            raise ValueError("default_requested_quantity must be positive")
        if max_history_bars <= 0:
            raise ValueError("max_history_bars must be positive")
        self.scanner = scanner
        self.allocator = allocator
        self.broker = broker
        self.ledger = ledger
        self.financial_journal = financial_journal
        self.agent_audit_journal = agent_audit_journal
        self.risk_engine = risk_engine
        self.starting_cash = starting_cash
        self.default_requested_quantity = default_requested_quantity
        self.requested_quantities = dict(requested_quantities or {})
        self.max_history_bars = max_history_bars
        self.metadata_provider = metadata_provider
        self.day_start_equity = starting_cash
        self._current_session_date = None
        self._histories: dict[tuple[str, str], list[NormalizedCandle]] = {}
        self._marks: dict[str, Decimal] = {}

    async def start(self) -> None:
        await self.broker.connect()

    async def stop(self) -> None:
        await self.broker.disconnect()

    async def on_batch(
        self,
        candles: list[NormalizedCandle] | tuple[NormalizedCandle, ...],
    ) -> MultiMarketPaperStep:
        if not candles:
            raise ValueError("multi-market paper batch cannot be empty")
        if any(not candle.closed for candle in candles):
            raise ValueError("multi-market paper runtime accepts only closed candles")
        close_times = {candle.close_time for candle in candles}
        if len(close_times) != 1:
            raise ValueError("all candles in a coordinated paper batch must share close_time")
        series_keys = [(candle.symbol, candle.timeframe) for candle in candles]
        if len(series_keys) != len(set(series_keys)):
            raise ValueError("paper batch cannot contain duplicate symbol/timeframe events")

        ordered = tuple(sorted(candles, key=lambda candle: (candle.symbol, candle.timeframe)))
        produced_fills: list[Fill] = []
        for candle in ordered:
            fills = await self.broker.on_candle(candle)
            for fill in fills:
                self.financial_journal.record_fill(
                    fill,
                    correlation_id=f"fill:{fill.order_id}",
                )
                self.ledger.apply_fill(fill)
                produced_fills.append(fill)

        for candle in ordered:
            self._marks[candle.symbol] = candle.close
        portfolio = self.ledger.snapshot(self._marks)
        close_time = ordered[0].close_time
        session_date = close_time.date()
        if self._current_session_date != session_date:
            self._current_session_date = session_date
            self.day_start_equity = portfolio.equity

        contexts: list[AgentContext] = []
        for candle in ordered:
            key = (candle.symbol, candle.timeframe)
            history = self._histories.setdefault(key, [])
            if history and candle.close_time <= history[-1].close_time:
                raise ValueError(
                    f"history for {candle.symbol}/{candle.timeframe} must be strictly increasing"
                )
            history.append(candle)
            if len(history) > self.max_history_bars:
                del history[: len(history) - self.max_history_bars]
            closed_history = tuple(history)
            metadata: dict[str, Any] = {
                "runtime": "multi_market_paper",
                "venue": candle.venue,
            }
            if self.metadata_provider is not None:
                metadata.update(self.metadata_provider(candle, closed_history))
            contexts.append(
                AgentContext(
                    correlation_id=(
                        f"multi-paper:{candle.symbol}:{candle.timeframe}:"
                        f"{candle.close_time.isoformat()}"
                    ),
                    symbol=candle.symbol,
                    decision_timeframe=candle.timeframe,
                    candles=closed_history,
                    created_at=candle.close_time,
                    metadata=metadata,
                )
            )

        scan = await self.scanner.scan(contexts)
        for candidate in scan.candidates:
            self.agent_audit_journal.record_round(
                context=candidate.context,
                round_result=candidate.round,
                memo=candidate.memo,
            )

        current_positions = {
            symbol: position.quantity for symbol, position in self.ledger.positions.items()
        }
        allocation = self.allocator.allocate(
            scan,
            portfolio=portfolio,
            day_start_equity=self.day_start_equity,
            default_requested_quantity=self.default_requested_quantity,
            requested_quantities=self.requested_quantities,
            current_positions=current_positions,
        )

        submitted: list[SubmittedPaperOrder] = []
        for item in allocation.approved:
            assert item.decision is not None and item.decision.order is not None
            order = item.decision.order
            correlation_id = item.candidate.context.correlation_id
            self.financial_journal.record_order_created(order, correlation_id=correlation_id)
            broker_order_id = await self.broker.submit_order(order)
            self.financial_journal.record_order_submitted(
                order.order_id,
                correlation_id=correlation_id,
            )
            submitted.append(
                SubmittedPaperOrder(
                    correlation_id=correlation_id,
                    order=order,
                    broker_order_id=broker_order_id,
                )
            )

        return MultiMarketPaperStep(
            close_time_iso=close_time.isoformat(),
            fills=tuple(produced_fills),
            scan=scan,
            allocation=allocation,
            submitted_orders=tuple(submitted),
            portfolio=portfolio,
        )

    def reconcile(self) -> ReconciliationReport:
        recovered = recover_financial_state(
            self.financial_journal.wal,
            starting_cash=self.starting_cash,
        )
        report = ReconciliationEngine().compare(
            recovered,
            broker_orders=self.broker.open_order_snapshots(),
            broker_positions=self.broker.position_snapshots(),
        )
        ReconciliationSupervisor().enforce(report, self.risk_engine)
        return report
