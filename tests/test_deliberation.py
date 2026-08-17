from datetime import UTC, datetime

from aura.agents.deliberation import AdversarialDeliberationEngine
from aura.agents.models import (
    AgentEvidence,
    AgentFailure,
    AgentRole,
    AgentRound,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.domain.models import SignalIntent


def _evidence(agent_id: str, role: AgentRole, intent: SignalIntent, thesis: str, flags=()):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return AgentEvidence(
        agent_id=agent_id,
        role=role,
        intent=intent,
        confidence=0.8,
        thesis=thesis,
        risk_flags=flags,
        sources=(
            EvidenceSource(
                source_id=f"source:{agent_id}",
                source_type=EvidenceSourceType.MARKET_DATA,
                observed_at=now,
                trust_score=1.0,
            ),
        ),
        generated_at=now,
    )


def test_deliberation_preserves_bull_bear_and_counterfactuals() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    round_result = AgentRound(
        correlation_id="round-1",
        evidence=(
            _evidence("technical", AgentRole.TECHNICAL, SignalIntent.LONG, "trend continuation"),
            _evidence("macro", AgentRole.MACRO_SENTIMENT, SignalIntent.SHORT, "macro headwind"),
            _evidence(
                "execution",
                AgentRole.EXECUTION_QUALITY,
                SignalIntent.FLAT,
                "spread elevated",
                flags=("spread_too_wide",),
            ),
        ),
        failures=(
            AgentFailure(
                agent_id="options",
                role=AgentRole.OPTIONS_VOLATILITY,
                error_type="timeout",
                message="provider timeout",
            ),
        ),
        started_at=now,
        completed_at=now,
    )

    memo = AdversarialDeliberationEngine().deliberate(round_result)
    assert memo.bull_case.supporting_agents == ("technical",)
    assert memo.bear_case.supporting_agents == ("macro",)
    assert memo.disagreement_ratio > 0
    assert len(memo.counterfactuals) == 2
    assert "spread elevated" in memo.neutral_arguments


def test_unanimous_direction_still_forces_invalidation_question() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    round_result = AgentRound(
        correlation_id="round-2",
        evidence=(
            _evidence("technical", AgentRole.TECHNICAL, SignalIntent.LONG, "trend"),
            _evidence("volume", AgentRole.VOLUME_VWAP, SignalIntent.LONG, "volume"),
        ),
        started_at=now,
        completed_at=now,
    )
    memo = AdversarialDeliberationEngine().deliberate(round_result)
    assert memo.bear_case.supporting_agents == ()
    assert any("invalidate" in item.description for item in memo.counterfactuals)
