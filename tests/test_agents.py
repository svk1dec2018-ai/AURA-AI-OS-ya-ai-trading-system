from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.domain.models import NormalizedCandle, SignalIntent


def _candle() -> NormalizedCandle:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return NormalizedCandle(
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


def _source(source_id: str, *, point_in_time_safe: bool = True) -> EvidenceSource:
    return EvidenceSource(
        source_id=source_id,
        source_type=EvidenceSourceType.MARKET_DATA,
        observed_at=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        trust_score=1.0,
        point_in_time_safe=point_in_time_safe,
    )


class BarrierAgent(SpecialistAgent):
    def __init__(
        self,
        *,
        agent_id: str,
        role: AgentRole,
        intent: SignalIntent,
        started: list[str],
        gate: asyncio.Event,
        expected: int,
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self.intent = intent
        self.started = started
        self.gate = gate
        self.expected = expected

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        self.started.append(self.agent_id)
        if len(self.started) == self.expected:
            self.gate.set()
        await self.gate.wait()
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=self.intent,
            confidence=0.8,
            thesis=f"{self.role.value} evidence",
            sources=(_source(f"source-{self.agent_id}"),),
            generated_at=context.candles[-1].close_time,
        )


class FailingAgent(SpecialistAgent):
    agent_id = "macro-broken"
    role = AgentRole.MACRO_SENTIMENT

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        raise RuntimeError(f"provider unavailable for {context.symbol}")


@pytest.mark.asyncio
async def test_specialists_run_concurrently_and_ceo_combines_evidence() -> None:
    started: list[str] = []
    gate = asyncio.Event()
    agents = [
        BarrierAgent(
            agent_id="htf",
            role=AgentRole.HTF_BIAS,
            intent=SignalIntent.LONG,
            started=started,
            gate=gate,
            expected=3,
        ),
        BarrierAgent(
            agent_id="smc",
            role=AgentRole.SMC_ICT,
            intent=SignalIntent.LONG,
            started=started,
            gate=gate,
            expected=3,
        ),
        BarrierAgent(
            agent_id="volume",
            role=AgentRole.VOLUME_VWAP,
            intent=SignalIntent.SHORT,
            started=started,
            gate=gate,
            expected=3,
        ),
    ]
    context = AgentContext(
        correlation_id="round-1",
        symbol="X",
        decision_timeframe="5m",
        candles=(_candle(),),
    )

    round_result = await MultiAgentOrchestrator(agents, timeout_seconds=1).run_round(context)
    assert set(started) == {"htf", "smc", "volume"}
    assert len(round_result.evidence) == 3
    assert round_result.failures == ()

    memo = CEOAggregator(min_agents=3, min_distinct_roles=3).synthesize(round_result)
    assert memo.quorum_met
    assert memo.intent == SignalIntent.LONG
    assert set(memo.supporting_agents) == {"htf", "smc"}
    assert memo.opposing_agents == ("volume",)


@pytest.mark.asyncio
async def test_one_agent_failure_does_not_cancel_other_specialists() -> None:
    started: list[str] = []
    gate = asyncio.Event()
    healthy = BarrierAgent(
        agent_id="technical",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
        started=started,
        gate=gate,
        expected=1,
    )
    context = AgentContext(
        correlation_id="round-2",
        symbol="X",
        decision_timeframe="5m",
        candles=(_candle(),),
    )

    result = await MultiAgentOrchestrator(
        [healthy, FailingAgent()],
        timeout_seconds=1,
    ).run_round(context)

    assert [item.agent_id for item in result.evidence] == ["technical"]
    assert [item.agent_id for item in result.failures] == ["macro-broken"]
    memo = CEOAggregator(min_agents=2, min_distinct_roles=2).synthesize(result)
    assert not memo.quorum_met
    assert memo.intent == SignalIntent.FLAT


def test_non_point_in_time_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentEvidence(
            agent_id="leaky-agent",
            role=AgentRole.TECHNICAL,
            intent=SignalIntent.LONG,
            confidence=0.9,
            thesis="uses future information",
            sources=(_source("future-source", point_in_time_safe=False),),
        )
