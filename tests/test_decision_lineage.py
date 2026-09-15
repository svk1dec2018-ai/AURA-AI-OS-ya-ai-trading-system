from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.deliberation import DeliberationCase, DeliberationMemo
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    AgentRound,
    CEODecisionMemo,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.risk_policy import AgentPolicyDecision
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.lineage.decision import DecisionLineageRecord
from aura.runtime.scanner import ScanCandidate


def _context(*, metadata: dict | None = None) -> AgentContext:
    close_time = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="BTC-USD",
        venue="COINBASE_PUBLIC",
        timeframe="1m",
        open_time=close_time - timedelta(minutes=1),
        close_time=close_time,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("12"),
        closed=True,
    )
    return AgentContext(
        correlation_id="lineage-1",
        symbol="BTC-USD",
        decision_timeframe="1m",
        candles=(candle,),
        metadata=metadata or {"market": "crypto", "regime": "trend"},
        created_at=close_time,
    )


def _round(context: AgentContext, *, source_time: datetime | None = None) -> AgentRound:
    observed = source_time or context.created_at
    evidence = AgentEvidence(
        agent_id="deterministic:technical:v1",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
        confidence=0.8,
        thesis="trend continuation",
        sources=(
            EvidenceSource(
                source_id="market:BTC-USD:1m",
                source_type=EvidenceSourceType.MARKET_DATA,
                observed_at=observed,
                trust_score=1.0,
            ),
        ),
        features={"ema_fast": 101.0, "ema_slow": 100.0},
        generated_at=observed,
    )
    return AgentRound(
        correlation_id=context.correlation_id,
        evidence=(evidence,),
        failures=(),
        started_at=context.created_at,
        completed_at=context.created_at,
    )


def _memo(context: AgentContext) -> CEODecisionMemo:
    return CEODecisionMemo(
        correlation_id=context.correlation_id,
        intent=SignalIntent.LONG,
        confidence=0.8,
        supporting_agents=("deterministic:technical:v1",),
        opposing_agents=(),
        abstaining_agents=(),
        risk_flags=(),
        rationale="test long",
        quorum_met=True,
        generated_at=context.created_at,
    )


def _deliberation() -> DeliberationMemo:
    return DeliberationMemo(
        bull_case=DeliberationCase(
            intent=SignalIntent.LONG,
            supporting_agents=("deterministic:technical:v1",),
            arguments=("trend continuation",),
            weighted_strength=0.8,
        ),
        bear_case=DeliberationCase(
            intent=SignalIntent.SHORT,
            supporting_agents=(),
            arguments=(),
            weighted_strength=0.0,
        ),
        neutral_arguments=(),
        counterfactuals=(),
        disagreement_ratio=0.0,
        evidence_count=1,
    )


def _policy() -> AgentPolicyDecision:
    return AgentPolicyDecision(allowed=True, reasons=())


def test_decision_lineage_is_deterministic_and_verifiable() -> None:
    context = _context()
    round_result = _round(context)
    memo = _memo(context)
    deliberation = _deliberation()
    policy = _policy()

    first = DecisionLineageRecord.build(
        context=context,
        round_result=round_result,
        memo=memo,
        data_quality=None,
        agent_policy=policy,
        deliberation=deliberation,
    )
    second = DecisionLineageRecord.build(
        context=context,
        round_result=round_result,
        memo=memo,
        data_quality=None,
        agent_policy=policy,
        deliberation=deliberation,
    )

    assert first == second
    assert first.lineage_hash == second.lineage_hash
    assert first.source_ids == ("market:BTC-USD:1m",)
    assert first.verify(
        context=context,
        round_result=round_result,
        memo=memo,
        data_quality=None,
        agent_policy=policy,
        deliberation=deliberation,
    )


def test_decision_lineage_detects_metadata_tampering() -> None:
    context = _context()
    record = DecisionLineageRecord.build(
        context=context,
        round_result=_round(context),
        memo=_memo(context),
        data_quality=None,
        agent_policy=_policy(),
        deliberation=_deliberation(),
    )
    tampered = _context(metadata={"market": "crypto", "regime": "chop"})

    assert not record.verify(
        context=tampered,
        round_result=_round(tampered),
        memo=_memo(tampered),
        data_quality=None,
        agent_policy=_policy(),
        deliberation=_deliberation(),
    )


def test_decision_lineage_rejects_future_observed_evidence() -> None:
    context = _context()
    future = context.created_at + timedelta(seconds=1)

    with pytest.raises(ValueError, match="observed after decision time"):
        DecisionLineageRecord.build(
            context=context,
            round_result=_round(context, source_time=future),
            memo=_memo(context),
            data_quality=None,
            agent_policy=_policy(),
            deliberation=_deliberation(),
        )


def test_scan_candidate_verifies_exact_lineage() -> None:
    context = _context()
    round_result = _round(context)
    memo = _memo(context)
    policy = _policy()
    deliberation = _deliberation()
    lineage = DecisionLineageRecord.build(
        context=context,
        round_result=round_result,
        memo=memo,
        data_quality=None,
        agent_policy=policy,
        deliberation=deliberation,
    )
    candidate = ScanCandidate(
        context=context,
        round=round_result,
        memo=memo,
        data_quality=None,
        agent_policy=policy,
        deliberation=deliberation,
        lineage=lineage,
    )

    assert candidate.verify_lineage()
