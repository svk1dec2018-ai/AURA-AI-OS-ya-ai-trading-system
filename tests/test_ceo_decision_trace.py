from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aura.agents.models import (
    AgentEvidence,
    AgentRole,
    AgentRound,
    DecisionReasonCode,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.orchestrator import CEOAggregator
from aura.domain.models import SignalIntent

_NOW = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)


def _evidence(
    agent_id: str,
    role: AgentRole,
    intent: SignalIntent,
    confidence: float,
    trust: float,
    *risk_flags: str,
) -> AgentEvidence:
    return AgentEvidence(
        agent_id=agent_id,
        role=role,
        intent=intent,
        confidence=confidence,
        thesis=f"{role.value} fixture",
        risk_flags=risk_flags,
        sources=(
            EvidenceSource(
                source_id=f"fixture:{agent_id}",
                source_type=EvidenceSourceType.MARKET_DATA,
                observed_at=_NOW,
                trust_score=trust,
            ),
        ),
        generated_at=_NOW,
    )


def _round(evidence: tuple[AgentEvidence, ...]) -> AgentRound:
    return AgentRound(
        correlation_id="phase10-trace",
        evidence=evidence,
        started_at=_NOW,
        completed_at=_NOW,
    )


def test_ceo_trace_is_reproducible_and_order_independent() -> None:
    evidence = (
        _evidence("technical", AgentRole.TECHNICAL, SignalIntent.LONG, 0.8, 0.9),
        _evidence("macro", AgentRole.MACRO_SENTIMENT, SignalIntent.SHORT, 0.4, 0.8),
        _evidence(
            "execution",
            AgentRole.EXECUTION_QUALITY,
            SignalIntent.FLAT,
            0.7,
            1.0,
            "wide_spread",
        ),
    )
    ceo = CEOAggregator(min_agents=3, min_distinct_roles=3)

    first = ceo.synthesize(_round(evidence))
    second = ceo.synthesize(_round(tuple(reversed(evidence))))

    assert first == second
    assert first.generated_at == _NOW
    assert first.decision_trace is not None
    assert first.decision_trace.reason_code == DecisionReasonCode.WEIGHTED_EVIDENCE
    assert first.decision_trace.evidence_count == 3
    assert first.decision_trace.distinct_role_count == 3
    assert first.decision_trace.long_score == pytest.approx(0.72)
    assert first.decision_trace.short_score == pytest.approx(0.32)
    assert first.decision_trace.execution_authority is False
    assert first.execution_authority is False
    assert first.risk_flags == ("wide_spread",)
    assert tuple(item.agent_id for item in first.decision_trace.contributions) == (
        "execution",
        "macro",
        "technical",
    )


def test_ceo_trace_explains_fail_closed_no_trade() -> None:
    evidence = (
        _evidence("technical", AgentRole.TECHNICAL, SignalIntent.LONG, 0.8, 1.0),
        _evidence("macro", AgentRole.MACRO_SENTIMENT, SignalIntent.SHORT, 0.8, 1.0),
        _evidence("regime", AgentRole.REGIME, SignalIntent.FLAT, 0.5, 1.0),
    )
    memo = CEOAggregator(
        min_agents=3,
        min_distinct_roles=3,
        min_directional_margin=0.15,
    ).synthesize(_round(evidence))

    assert memo.intent == SignalIntent.FLAT
    assert memo.quorum_met is True
    assert memo.decision_trace is not None
    assert (
        memo.decision_trace.reason_code
        == DecisionReasonCode.DIRECTIONAL_DISAGREEMENT
    )
    assert set(memo.opposing_agents) == {"technical", "macro"}
    assert "directional disagreement" in memo.rationale


def test_ceo_rejects_invalid_role_weights() -> None:
    with pytest.raises(ValueError, match="finite positive"):
        CEOAggregator(role_weights={AgentRole.TECHNICAL: 0.0})
    with pytest.raises(ValueError, match="finite positive"):
        CEOAggregator(role_weights={AgentRole.TECHNICAL: float("nan")})
