from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aura.agents.audit import AgentAuditJournal
from aura.agents.models import AgentContext
from aura.agents.service import MultiAgentDecisionOutcome, MultiAgentDecisionService
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

ContextMetadataProvider = Callable[
    [NormalizedCandle, tuple[NormalizedCandle, ...]],
    dict[str, Any],
]


@dataclass(slots=True, frozen=True)
class PaperRuntimeStep:
    candle: NormalizedCandle
    fills: tuple[Fill, ...]
    decision: MultiAgentDecisionOutcome
    submitted_order: OrderRequest | None
    broker_order_id: str | None
    portfolio: PortfolioSnapshot


class MultiAgentPaperRuntime:
    """End-to-end AURA paper loop using the governed production-style path.

    Each closed candle first advances orders that were already pending at the
    paper broker. Fills are written to the financial WAL before they mutate the
    local ledger. Rolling per-symbol/timeframe history is then supplied to the
    specialist team, allowing technical/structure/regime agents to complete
    their causal warmups. New orders are submitted only after the current candle
    has been processed, so they cannot fill on the same bar that generated them.
    """

    def __init__(
        self,
        *,
        decision_service: MultiAgentDecisionService,
        broker: PaperBroker,
        ledger: PortfolioLedger,
        financial_journal: FinancialEventJournal,
        agent_audit_journal: AgentAuditJournal,
        risk_engine: RiskEngine,
        starting_cash: Decimal,
        requested_quantity: Decimal,
        max_history_bars: int = 5000,
        context_metadata_provider: ContextMetadataProvider | None = None,
    ) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        if requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive")
        if max_history_bars <= 0:
            raise ValueError("max_history_bars must be positive")
        self.decision_service = decision_service
        self.broker = broker
        self.ledger = ledger
        self.financial_journal = financial_journal
        self.agent_audit_journal = agent_audit_journal
        self.risk_engine = risk_engine
        self.starting_cash = starting_cash
        self.requested_quantity = requested_quantity
        self.max_history_bars = max_history_bars
        self.context_metadata_provider = context_metadata_provider
        self.day_start_equity = starting_cash
        self._current_session_date = None
        self._histories: dict[tuple[str, str], list[NormalizedCandle]] = {}
        self._marks: dict[str, Decimal] = {}

    async def start(self) -> None:
        await self.broker.connect()

    async def stop(self) -> None:
        await self.broker.disconnect()

    async def on_candle(self, candle: NormalizedCandle) -> PaperRuntimeStep:
        if not candle.closed:
            raise ValueError("paper runtime accepts only closed candles")

        fills = await self.broker.on_candle(candle)
        for fill in fills:
            self.financial_journal.record_fill(
                fill,
                correlation_id=f"fill:{fill.order_id}",
            )
            self.ledger.apply_fill(fill)

        self._marks[candle.symbol] = candle.close
        portfolio = self.ledger.snapshot(self._marks)
        session_date = candle.close_time.date()
        if self._current_session_date != session_date:
            self._current_session_date = session_date
            self.day_start_equity = portfolio.equity

        history_key = (candle.symbol, candle.timeframe)
        history = self._histories.setdefault(history_key, [])
        if history and candle.close_time <= history[-1].close_time:
            raise ValueError("paper runtime candle history must be strictly increasing")
        history.append(candle)
        if len(history) > self.max_history_bars:
            del history[: len(history) - self.max_history_bars]
        closed_history = tuple(history)

        metadata: dict[str, Any] = {"runtime": "paper", "venue": candle.venue}
        if self.context_metadata_provider is not None:
            metadata.update(self.context_metadata_provider(candle, closed_history))

        current_position = self.ledger.positions.get(candle.symbol)
        current_quantity = current_position.quantity if current_position is not None else Decimal(0)
        context = AgentContext(
            correlation_id=f"paper:{candle.symbol}:{candle.timeframe}:{candle.close_time.isoformat()}",
            symbol=candle.symbol,
            decision_timeframe=candle.timeframe,
            candles=closed_history,
            created_at=candle.close_time,
            metadata=metadata,
        )
        decision = await self.decision_service.evaluate(
            context=context,
            portfolio=portfolio,
            day_start_equity=self.day_start_equity,
            venue=candle.venue,
            requested_quantity=self.requested_quantity,
            current_position_quantity=current_quantity,
        )
        self.agent_audit_journal.record_round(
            context=context,
            round_result=decision.round,
            memo=decision.memo,
        )

        submitted_order: OrderRequest | None = None
        broker_order_id: str | None = None
        if decision.governed_result is not None and decision.governed_result.order is not None:
            submitted_order = decision.governed_result.order
            correlation_id = context.correlation_id
            self.financial_journal.record_order_created(
                submitted_order,
                correlation_id=correlation_id,
            )
            broker_order_id = await self.broker.submit_order(submitted_order)
            self.financial_journal.record_order_submitted(
                submitted_order.order_id,
                correlation_id=correlation_id,
            )

        return PaperRuntimeStep(
            candle=candle,
            fills=fills,
            decision=decision,
            submitted_order=submitted_order,
            broker_order_id=broker_order_id,
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
