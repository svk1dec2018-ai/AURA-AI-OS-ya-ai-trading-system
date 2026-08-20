from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aura.agents.audit import AgentAuditJournal
from aura.agents.models import AgentContext, AgentRole, EvidenceSource, EvidenceSourceType
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.agents.providers import ProviderAnalysis, ProviderBackedSpecialist, ReasoningProvider
from aura.agents.service import MultiAgentDecisionService
from aura.core.pipeline import DecisionPipeline
from aura.data.quality import CandleQualityGate, DataQualityPolicy
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.execution.paper import PaperBroker
from aura.persistence.recovery import FinancialEventJournal, recover_financial_state
from aura.persistence.wal import JsonlWriteAheadLog
from aura.portfolio.ledger import PortfolioLedger
from aura.risk.engine import RiskEngine, RiskLimits
from aura.runtime.paper import MultiAgentPaperRuntime
from aura.strategy.ema import EmaCrossStrategy


class LongProvider(ReasoningProvider):
    def __init__(self, provider_id: str, model_id: str) -> None:
        self.provider_id = provider_id
        self.model_id = model_id

    async def analyze(self, *, role: AgentRole, context: AgentContext) -> ProviderAnalysis:
        return ProviderAnalysis(
            intent=SignalIntent.LONG,
            confidence=0.8,
            thesis=f"{role.value} confirms long",
            sources=(
                EvidenceSource(
                    source_id=f"market:{context.symbol}:{context.candles[-1].close_time.isoformat()}",
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=context.candles[-1].close_time,
                    trust_score=1.0,
                ),
            ),
        )


def _candle(minute: int, open_price: str, close_price: str) -> NormalizedCandle:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    open_value = Decimal(open_price)
    close_value = Decimal(close_price)
    return NormalizedCandle(
        symbol="X",
        venue="PAPER",
        timeframe="1m",
        open_time=start,
        close_time=start + timedelta(minutes=1),
        open=open_value,
        high=max(open_value, close_value),
        low=min(open_value, close_value),
        close=close_value,
        volume=Decimal(100),
        closed=True,
    )


def _decision_service(risk: RiskEngine) -> MultiAgentDecisionService:
    agents = [
        ProviderBackedSpecialist(
            provider=LongProvider("a", "htf-model"),
            role=AgentRole.HTF_BIAS,
        ),
        ProviderBackedSpecialist(
            provider=LongProvider("b", "smc-model"),
            role=AgentRole.SMC_ICT,
        ),
        ProviderBackedSpecialist(
            provider=LongProvider("c", "volume-model"),
            role=AgentRole.VOLUME_VWAP,
        ),
    ]
    return MultiAgentDecisionService(
        orchestrator=MultiAgentOrchestrator(agents, timeout_seconds=1),
        ceo=CEOAggregator(min_agents=3, min_distinct_roles=3),
        decision_pipeline=DecisionPipeline(EmaCrossStrategy(fast=2, slow=3), risk),
        data_quality_gate=CandleQualityGate(
            DataQualityPolicy(
                expected_interval=timedelta(minutes=1),
                max_staleness=timedelta(minutes=1),
            )
        ),
    )


@pytest.mark.asyncio
async def test_runtime_defers_fill_to_next_candle_and_reconciles(tmp_path: Path) -> None:
    starting_cash = Decimal(10000)
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(100),
        )
    )
    financial_wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    audit_wal = JsonlWriteAheadLog(tmp_path / "agent-audit.wal", fsync=False)
    ledger = PortfolioLedger(starting_cash)
    broker = PaperBroker()
    runtime = MultiAgentPaperRuntime(
        decision_service=_decision_service(risk),
        broker=broker,
        ledger=ledger,
        financial_journal=FinancialEventJournal(financial_wal),
        agent_audit_journal=AgentAuditJournal(audit_wal),
        risk_engine=risk,
        starting_cash=starting_cash,
        requested_quantity=Decimal(1),
    )
    await runtime.start()

    first = await runtime.on_candle(_candle(0, "100", "101"))
    assert first.fills == ()
    assert first.submitted_order is not None
    assert first.broker_order_id is not None
    assert ledger.positions == {}
    assert len(audit_wal.read_all()) == 1

    second = await runtime.on_candle(_candle(1, "102", "103"))
    assert len(second.fills) == 1
    assert second.fills[0].order_id == first.submitted_order.order_id
    assert second.fills[0].price == Decimal(102)
    assert ledger.positions["X"].quantity == Decimal(1)
    assert second.portfolio.equity == Decimal(10001)
    assert len(audit_wal.read_all()) == 2

    recovered = recover_financial_state(financial_wal, starting_cash=starting_cash)
    assert recovered.ledger.positions["X"].quantity == Decimal(1)
    assert runtime.reconcile().safe_for_new_risk
    assert not risk.kill_switch

    await runtime.stop()
