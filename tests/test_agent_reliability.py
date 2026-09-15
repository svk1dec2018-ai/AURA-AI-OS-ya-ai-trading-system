from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import aura.agents.reliability as reliability_module
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    AgentRound,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.orchestrator import CEOAggregator
from aura.agents.reliability import AgentReliabilityTracker
from aura.domain.models import NormalizedCandle, SignalIntent


def _evidence(
    *,
    agent_id: str,
    role: AgentRole,
    intent: SignalIntent,
    confidence: float = 0.9,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> AgentEvidence:
    now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    features = {}
    if provider_id and model_id:
        features = {"provider_id": provider_id, "model_id": model_id}
    return AgentEvidence(
        agent_id=agent_id,
        role=role,
        intent=intent,
        confidence=confidence,
        thesis="test evidence",
        sources=(
            EvidenceSource(
                source_id="test-feed",
                source_type=EvidenceSourceType.MARKET_DATA,
                observed_at=now,
                trust_score=1.0,
            ),
        ),
        features=features,
        generated_at=now,
    )


def _context() -> AgentContext:
    close_time = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="BTC-USD",
        venue="COINBASE_PUBLIC",
        timeframe="1m",
        open_time=close_time - timedelta(minutes=1),
        close_time=close_time,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal("100.5"),
        volume=Decimal(10),
        closed=True,
    )
    return AgentContext(
        correlation_id="reliability-test",
        symbol="BTC-USD",
        decision_timeframe="1m",
        candles=(candle,),
        metadata={"regime": "trend"},
        created_at=close_time,
    )


def test_tracker_learns_good_and_bad_agents_and_persists(tmp_path) -> None:
    path = tmp_path / "agent_reliability.jsonl"
    tracker = AgentReliabilityTracker(path)
    good = _evidence(
        agent_id="ai-good",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
        provider_id="ollama",
        model_id="good-model",
    )
    bad = _evidence(
        agent_id="ai-bad",
        role=AgentRole.SMC_ICT,
        intent=SignalIntent.SHORT,
        provider_id="ollama",
        model_id="bad-model",
    )
    start = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    for index in range(30):
        decision_time = start + timedelta(minutes=index)
        outcome_time = decision_time + timedelta(minutes=5)
        tracker.record_evidence_outcome(
            good,
            observation_prefix=f"good-{index}",
            market="COINBASE_PUBLIC",
            regime="trend",
            realized_intent=SignalIntent.LONG,
            decision_time=decision_time,
            outcome_observed_at=outcome_time,
        )
        tracker.record_evidence_outcome(
            bad,
            observation_prefix=f"bad-{index}",
            market="COINBASE_PUBLIC",
            regime="trend",
            realized_intent=SignalIntent.LONG,
            decision_time=decision_time,
            outcome_observed_at=outcome_time,
        )

    assert tracker.vote_weight(good, market="COINBASE_PUBLIC", regime="trend") > 1.0
    assert tracker.vote_weight(bad, market="COINBASE_PUBLIC", regime="trend") < 1.0
    assert tracker.observation_count == 60

    restored = AgentReliabilityTracker(path)
    assert restored.observation_count == 60
    assert restored.vote_weight(good, market="COINBASE_PUBLIC", regime="trend") > 1.0


def test_ceo_uses_contextual_reliability_to_break_equal_confidence_vote() -> None:
    tracker = AgentReliabilityTracker(prior_strength=2.0)
    long_agent = _evidence(
        agent_id="long-agent",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
    )
    short_agent = _evidence(
        agent_id="short-agent",
        role=AgentRole.SMC_ICT,
        intent=SignalIntent.SHORT,
    )
    start = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
    for index in range(20):
        decision_time = start + timedelta(minutes=index)
        outcome_time = decision_time + timedelta(minutes=1)
        tracker.record_evidence_outcome(
            long_agent,
            observation_prefix=f"long-{index}",
            market="COINBASE_PUBLIC",
            regime="trend",
            realized_intent=SignalIntent.LONG,
            decision_time=decision_time,
            outcome_observed_at=outcome_time,
        )
        tracker.record_evidence_outcome(
            short_agent,
            observation_prefix=f"short-{index}",
            market="COINBASE_PUBLIC",
            regime="trend",
            realized_intent=SignalIntent.LONG,
            decision_time=decision_time,
            outcome_observed_at=outcome_time,
        )

    now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    round_result = AgentRound(
        correlation_id="reliability-test",
        evidence=(long_agent, short_agent),
        started_at=now,
        completed_at=now,
    )
    memo = CEOAggregator(
        min_agents=2,
        min_distinct_roles=2,
        min_directional_margin=0.0,
        reliability_tracker=tracker,
    ).synthesize(round_result, context=_context())

    assert memo.intent == SignalIntent.LONG
    assert "avg_reliability_weight" in memo.rationale


def test_persistent_reliability_observation_is_fsynced(tmp_path, monkeypatch) -> None:
    fsync_calls: list[int] = []
    monkeypatch.setattr(reliability_module.os, "fsync", fsync_calls.append)
    tracker = AgentReliabilityTracker(tmp_path / "durable_reliability.jsonl")
    evidence = _evidence(
        agent_id="durable-agent",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
    )
    decision_time = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)

    assert tracker.record_evidence_outcome(
        evidence,
        observation_prefix="durable-1",
        market="COINBASE_PUBLIC",
        regime="trend",
        realized_intent=SignalIntent.LONG,
        decision_time=decision_time,
        outcome_observed_at=decision_time + timedelta(minutes=1),
    )
    assert len(fsync_calls) == 1


def test_reliability_write_failure_does_not_claim_in_memory_success(
    tmp_path,
    monkeypatch,
) -> None:
    tracker = AgentReliabilityTracker(tmp_path / "failed_reliability.jsonl")
    evidence = _evidence(
        agent_id="durable-agent",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
    )
    decision_time = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)

    def fail_fsync(_fd: int) -> None:
        raise OSError("disk sync failed")

    monkeypatch.setattr(reliability_module.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="disk sync failed"):
        tracker.record_evidence_outcome(
            evidence,
            observation_prefix="durable-failure",
            market="COINBASE_PUBLIC",
            regime="trend",
            realized_intent=SignalIntent.LONG,
            decision_time=decision_time,
            outcome_observed_at=decision_time + timedelta(minutes=1),
        )
    assert tracker.observation_count == 0
