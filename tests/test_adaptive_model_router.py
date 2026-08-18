from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.adaptive_model_router import (
    AdaptiveModelRouter,
    RoutedProviderBackedSpecialist,
)
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.providers import ProviderAnalysis, ReasoningProvider
from aura.agents.reliability import AgentReliabilityTracker
from aura.domain.models import NormalizedCandle, SignalIntent


class _Provider(ReasoningProvider):
    def __init__(self, model_id: str, intent: SignalIntent = SignalIntent.LONG) -> None:
        self.provider_id = "local"
        self.model_id = model_id
        self.intent = intent

    async def analyze(self, *, role: AgentRole, context: AgentContext) -> ProviderAnalysis:
        return ProviderAnalysis(
            intent=self.intent,
            confidence=0.8,
            thesis=f"{self.model_id} {role.value}",
            sources=(
                EvidenceSource(
                    source_id=f"test:{self.model_id}",
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=context.created_at,
                    trust_score=1.0,
                ),
            ),
        )


def _context(*, correlation_id: str = "route-1") -> AgentContext:
    close_time = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="BTC-USD",
        venue="COINBASE_PUBLIC",
        timeframe="1m",
        open_time=close_time - timedelta(minutes=1),
        close_time=close_time,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("20"),
        closed=True,
    )
    return AgentContext(
        correlation_id=correlation_id,
        symbol="BTC-USD",
        decision_timeframe="1m",
        candles=(candle,),
        created_at=close_time,
        metadata={"market": "CRYPTO", "regime": "trend"},
    )


def _evidence(
    *,
    agent_id: str,
    model_id: str,
    role: AgentRole,
    intent: SignalIntent,
    confidence: float = 0.9,
) -> AgentEvidence:
    now = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
    return AgentEvidence(
        agent_id=agent_id,
        role=role,
        intent=intent,
        confidence=confidence,
        thesis="training observation",
        sources=(
            EvidenceSource(
                source_id="training",
                source_type=EvidenceSourceType.MARKET_DATA,
                observed_at=now,
                trust_score=1.0,
            ),
        ),
        features={"provider_id": "local", "model_id": model_id},
        generated_at=now,
    )


def _record_many(
    tracker: AgentReliabilityTracker,
    *,
    evidence: AgentEvidence,
    correct: bool,
    count: int,
    prefix: str,
) -> None:
    start = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
    realized = evidence.intent
    if not correct:
        realized = (
            SignalIntent.SHORT
            if evidence.intent == SignalIntent.LONG
            else SignalIntent.LONG
        )
    for index in range(count):
        decision_time = start + timedelta(minutes=index)
        tracker.record_evidence_outcome(
            evidence,
            observation_prefix=f"{prefix}-{index}",
            market="CRYPTO",
            regime="trend",
            realized_intent=realized,
            decision_time=decision_time,
            outcome_observed_at=decision_time + timedelta(minutes=5),
        )


def test_router_exploits_role_specific_forward_reliability() -> None:
    tracker = AgentReliabilityTracker(prior_strength=2.0)
    provider_a = _Provider("model-a")
    provider_b = _Provider("model-b")
    good_technical = _evidence(
        agent_id="slot-a",
        model_id="model-a",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
    )
    bad_technical = _evidence(
        agent_id="slot-b",
        model_id="model-b",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
    )
    strong_macro_b = _evidence(
        agent_id="macro-b",
        model_id="model-b",
        role=AgentRole.MACRO_SENTIMENT,
        intent=SignalIntent.LONG,
    )
    _record_many(
        tracker,
        evidence=good_technical,
        correct=True,
        count=30,
        prefix="good-tech",
    )
    _record_many(
        tracker,
        evidence=bad_technical,
        correct=False,
        count=30,
        prefix="bad-tech",
    )
    _record_many(
        tracker,
        evidence=strong_macro_b,
        correct=True,
        count=60,
        prefix="good-macro",
    )

    router = AdaptiveModelRouter(
        (provider_a, provider_b),
        tracker,
        exploration_strength=0.0,
    )
    selected = router.select(
        role=AgentRole.TECHNICAL,
        context=_context(),
    )

    assert selected.provider.model_id == "model-a"
    assert selected.posterior_reliability > 0.5
    assert selected.samples == 30


def test_router_keeps_multiple_opinion_slots_diverse() -> None:
    tracker = AgentReliabilityTracker()
    providers = (_Provider("a"), _Provider("b"), _Provider("c"))
    router = AdaptiveModelRouter(providers, tracker, exploration_strength=0.12)
    context = _context(correlation_id="diversity")

    first = router.select(role=AgentRole.SMC_ICT, context=context, opinion_slot=0)
    second = router.select(role=AgentRole.SMC_ICT, context=context, opinion_slot=1)
    third = router.select(role=AgentRole.SMC_ICT, context=context, opinion_slot=2)

    assert len({first.model_key, second.model_key, third.model_key}) == 3


def test_router_gives_under_tested_model_exploration_bonus() -> None:
    tracker = AgentReliabilityTracker(prior_strength=2.0)
    tested = _Provider("tested")
    challenger = _Provider("challenger")
    tested_evidence = _evidence(
        agent_id="tested-slot",
        model_id="tested",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
        confidence=0.55,
    )
    _record_many(
        tracker,
        evidence=tested_evidence,
        correct=True,
        count=100,
        prefix="tested",
    )
    router = AdaptiveModelRouter(
        (tested, challenger),
        tracker,
        exploration_strength=0.20,
    )
    ranked = router.rank(role=AgentRole.TECHNICAL, context=_context())
    by_key = {item.model_key: item for item in ranked}

    assert (
        by_key["local:challenger"].exploration_bonus
        > by_key["local:tested"].exploration_bonus
    )


@pytest.mark.asyncio
async def test_routed_specialist_exposes_selected_model_and_route_audit_features() -> None:
    tracker = AgentReliabilityTracker()
    router = AdaptiveModelRouter((_Provider("a"), _Provider("b")), tracker)
    specialist = RoutedProviderBackedSpecialist(
        router=router,
        role=AgentRole.CROSS_MARKET,
        opinion_slot=0,
    )

    evidence = await specialist.analyze(_context())

    assert evidence.agent_id.startswith("ai-council:router:cross_market")
    assert evidence.features["provider_id"] == "local"
    assert evidence.features["model_id"] in {"a", "b"}
    assert "router_score" in evidence.features
    assert "router_exploration_bonus" in evidence.features
