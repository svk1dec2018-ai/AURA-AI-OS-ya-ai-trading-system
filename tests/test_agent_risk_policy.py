from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.agents.risk_policy import AgentRiskPolicy
from aura.agents.service import MultiAgentDecisionService
from aura.core.pipeline import DecisionPipeline
from aura.data.quality import CandleQualityGate, DataQualityPolicy
from aura.domain.models import NormalizedCandle, PortfolioSnapshot, SignalIntent
from aura.risk.engine import RiskEngine, RiskLimits
from aura.strategy.ema import EmaCrossStrategy


class PolicyAgent(SpecialistAgent):
    def __init__(
        self,
        *,
        agent_id: str,
        role: AgentRole,
        risk_flags: tuple[str, ...] = (),
        fail: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self.risk_flags = risk_flags
        self.fail = fail

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        if self.fail:
            raise RuntimeError("required specialist unavailable")
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=SignalIntent.LONG if self.role != AgentRole.REGIME else SignalIntent.FLAT,
            confidence=0.8,
            thesis=f"{self.role.value} evidence",
            risk_flags=self.risk_flags,
            sources=(
                EvidenceSource(
                    source_id=f"source:{self.agent_id}",
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=context.candles[-1].close_time,
                    trust_score=1.0,
                ),
            ),
            generated_at=context.created_at,
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
        volume=Decimal(100),
        closed=True,
    )
    return AgentContext(
        correlation_id="policy-round",
        symbol="X",
        decision_timeframe="5m",
        candles=(candle,),
        created_at=candle.close_time,
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


def _agents(
    *,
    spread_flag: bool = False,
    fail_htf: bool = False,
    technical_warmup: bool = False,
) -> list[SpecialistAgent]:
    return [
        PolicyAgent(agent_id="htf", role=AgentRole.HTF_BIAS, fail=fail_htf),
        PolicyAgent(agent_id="smc", role=AgentRole.SMC_ICT),
        PolicyAgent(
            agent_id="technical",
            role=AgentRole.TECHNICAL,
            risk_flags=("technical_warmup",) if technical_warmup else (),
        ),
        PolicyAgent(agent_id="volume", role=AgentRole.VOLUME_VWAP),
        PolicyAgent(agent_id="regime", role=AgentRole.REGIME),
        PolicyAgent(
            agent_id="execution",
            role=AgentRole.EXECUTION_QUALITY,
            risk_flags=("spread_too_wide",) if spread_flag else (),
        ),
    ]


def _service(agents: list[SpecialistAgent]) -> MultiAgentDecisionService:
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(100),
        )
    )
    return MultiAgentDecisionService(
        orchestrator=MultiAgentOrchestrator(agents, timeout_seconds=1),
        ceo=CEOAggregator(min_agents=5, min_distinct_roles=5),
        decision_pipeline=DecisionPipeline(EmaCrossStrategy(fast=2, slow=3), risk),
        data_quality_gate=CandleQualityGate(
            DataQualityPolicy(
                expected_interval=timedelta(minutes=5),
                max_staleness=timedelta(days=36500),
            )
        ),
        agent_risk_policy=AgentRiskPolicy(),
    )


@pytest.mark.asyncio
async def test_clean_required_evidence_reaches_independent_financial_risk() -> None:
    outcome = await _service(_agents()).evaluate(
        context=_context(),
        portfolio=_portfolio(),
        day_start_equity=Decimal(10000),
        venue="TEST",
        requested_quantity=Decimal(1),
    )

    assert outcome.memo.intent == SignalIntent.LONG
    assert outcome.agent_policy_decision is not None
    assert outcome.agent_policy_decision.allowed
    assert outcome.governed_result is not None
    assert outcome.governed_result.risk.approved
    assert outcome.governed_result.order is not None


@pytest.mark.asyncio
async def test_wide_spread_hard_blocks_even_when_ceo_is_long() -> None:
    outcome = await _service(_agents(spread_flag=True)).evaluate(
        context=_context(),
        portfolio=_portfolio(),
        day_start_equity=Decimal(10000),
        venue="TEST",
        requested_quantity=Decimal(1),
    )

    assert outcome.memo.intent == SignalIntent.LONG
    assert outcome.agent_policy_decision is not None
    assert not outcome.agent_policy_decision.allowed
    assert outcome.agent_policy_decision.hard_block_flags == ("spread_too_wide",)
    assert outcome.governed_result is None


@pytest.mark.asyncio
async def test_required_specialist_failure_blocks_candidate() -> None:
    outcome = await _service(_agents(fail_htf=True)).evaluate(
        context=_context(),
        portfolio=_portfolio(),
        day_start_equity=Decimal(10000),
        venue="TEST",
        requested_quantity=Decimal(1),
    )

    assert outcome.agent_policy_decision is not None
    assert not outcome.agent_policy_decision.allowed
    assert AgentRole.HTF_BIAS in outcome.agent_policy_decision.missing_required_roles
    assert AgentRole.HTF_BIAS in outcome.agent_policy_decision.failed_required_roles
    assert outcome.governed_result is None


@pytest.mark.asyncio
async def test_required_role_warmup_packet_is_present_but_unavailable_and_blocks() -> None:
    outcome = await _service(_agents(technical_warmup=True)).evaluate(
        context=_context(),
        portfolio=_portfolio(),
        day_start_equity=Decimal(10000),
        venue="TEST",
        requested_quantity=Decimal(1),
    )

    assert outcome.agent_policy_decision is not None
    assert not outcome.agent_policy_decision.allowed
    assert outcome.agent_policy_decision.missing_required_roles == ()
    assert AgentRole.TECHNICAL in outcome.agent_policy_decision.unavailable_required_roles
    assert outcome.governed_result is None
