from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.models import AgentContext, AgentRole, EvidenceSource, EvidenceSourceType
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.agents.providers import ProviderAnalysis, ProviderBackedSpecialist, ReasoningProvider
from aura.agents.service import MultiAgentDecisionService
from aura.core.pipeline import DecisionPipeline
from aura.domain.models import NormalizedCandle, PortfolioSnapshot, SignalIntent
from aura.risk.engine import RiskEngine, RiskLimits
from aura.strategy.ema import EmaCrossStrategy


class StaticProvider(ReasoningProvider):
    def __init__(self, provider_id: str, model_id: str, intent: SignalIntent) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self.intent = intent

    async def analyze(self, *, role: AgentRole, context: AgentContext) -> ProviderAnalysis:
        return ProviderAnalysis(
            intent=self.intent,
            confidence=0.8,
            thesis=f"{self.model_id} sees {self.intent.value} from {role.value}",
            sources=(
                EvidenceSource(
                    source_id=f"{context.symbol}:{context.candles[-1].close_time.isoformat()}",
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=context.candles[-1].close_time,
                    trust_score=1.0,
                ),
            ),
        )


def _context() -> AgentContext:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="X",
        venue="TEST",
        timeframe="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
        open=Decimal(100),
        high=Decimal(102),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(1000),
        closed=True,
    )
    return AgentContext(
        correlation_id="multi-model-round",
        symbol="X",
        decision_timeframe="5m",
        candles=(candle,),
    )


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=Decimal(10000),
        equity=Decimal(10000),
        gross_exposure=Decimal(0),
        net_exposure=Decimal(0),
        realized_pnl=Decimal(0),
        unrealized_pnl=Decimal(0),
        peak_equity=Decimal(10000),
        drawdown_pct=Decimal(0),
    )


def _service(risk: RiskEngine) -> MultiAgentDecisionService:
    agents = [
        ProviderBackedSpecialist(
            provider=StaticProvider("provider-a", "model-a", SignalIntent.LONG),
            role=AgentRole.HTF_BIAS,
        ),
        ProviderBackedSpecialist(
            provider=StaticProvider("provider-b", "model-b", SignalIntent.LONG),
            role=AgentRole.SMC_ICT,
        ),
        ProviderBackedSpecialist(
            provider=StaticProvider("provider-c", "model-c", SignalIntent.SHORT),
            role=AgentRole.VOLUME_VWAP,
        ),
    ]
    pipeline = DecisionPipeline(EmaCrossStrategy(fast=2, slow=3), risk)
    return MultiAgentDecisionService(
        orchestrator=MultiAgentOrchestrator(agents, timeout_seconds=1),
        ceo=CEOAggregator(min_agents=3, min_distinct_roles=3),
        decision_pipeline=pipeline,
    )


@pytest.mark.asyncio
async def test_multi_model_ceo_output_is_resized_by_independent_risk_engine() -> None:
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(2),
            max_gross_exposure_pct=Decimal(100),
        )
    )
    outcome = await _service(risk).evaluate(
        context=_context(),
        portfolio=_portfolio(),
        day_start_equity=Decimal(10000),
        venue="TEST",
        requested_quantity=Decimal(10),
    )

    assert outcome.memo.intent == SignalIntent.LONG
    assert outcome.governed_result is not None
    assert outcome.governed_result.risk.approved
    assert outcome.governed_result.order is not None
    assert outcome.governed_result.order.quantity == Decimal(200) / Decimal(101)
    assert outcome.governed_result.order.quantity < Decimal(10)


@pytest.mark.asyncio
async def test_kill_switch_blocks_multi_agent_order_even_when_ceo_is_directional() -> None:
    risk = RiskEngine(RiskLimits())
    risk.engage_kill_switch("reconciliation mismatch")
    outcome = await _service(risk).evaluate(
        context=_context(),
        portfolio=_portfolio(),
        day_start_equity=Decimal(10000),
        venue="TEST",
        requested_quantity=Decimal(1),
    )

    assert outcome.memo.intent == SignalIntent.LONG
    assert outcome.governed_result is not None
    assert not outcome.governed_result.risk.approved
    assert outcome.governed_result.order is None
    assert "kill switch" in outcome.governed_result.risk.reason
