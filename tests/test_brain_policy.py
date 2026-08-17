from datetime import UTC, datetime

from aura.agents.deliberation import DeliberationCase, DeliberationMemo
from aura.agents.models import AgentEvidence, AgentRole, AgentRound, CEODecisionMemo
from aura.domain.models import SignalIntent
from aura.evolution.brain_policy import (
    BRAIN_POLICY_GENE_SPACE,
    AuraBrainPolicy,
    BrainPolicyGate,
)


def _round() -> AgentRound:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    evidence = tuple(
        AgentEvidence(
            agent_id=f"a{i}",
            role=role,
            intent=SignalIntent.LONG,
            confidence=0.8,
            rationale="support",
            observed_at=now,
        )
        for i, role in enumerate(
            (
                AgentRole.HTF_BIAS,
                AgentRole.SMC_ICT,
                AgentRole.TECHNICAL,
                AgentRole.VOLUME_VWAP,
                AgentRole.REGIME,
                AgentRole.EXECUTION_QUALITY,
            )
        )
    )
    return AgentRound(
        correlation_id="x",
        evidence=evidence,
        failures=(),
        started_at=now,
        completed_at=now,
    )


def _memo(confidence: float = 0.8) -> CEODecisionMemo:
    return CEODecisionMemo(
        correlation_id="x",
        intent=SignalIntent.LONG,
        confidence=confidence,
        supporting_agents=("a1", "a2"),
        opposing_agents=(),
        abstaining_agents=(),
        risk_flags=(),
        rationale="candidate",
        quorum_met=True,
        generated_at=datetime(2026, 8, 17, tzinfo=UTC),
    )


def _deliberation(disagreement: float) -> DeliberationMemo:
    empty = DeliberationCase(
        label="case",
        arguments=(),
        aggregate_confidence=0.0,
    )
    return DeliberationMemo(
        bull_case=empty,
        bear_case=empty,
        neutral_arguments=(),
        counterfactuals=(),
        disagreement_ratio=disagreement,
        evidence_count=6,
    )


def test_brain_policy_gene_space_contains_no_financial_risk_authority() -> None:
    names = {item.name for item in BRAIN_POLICY_GENE_SPACE}
    forbidden = {
        "max_daily_loss_pct",
        "max_drawdown_pct",
        "max_order_notional_pct",
        "max_gross_exposure_pct",
        "leverage",
        "kill_switch",
    }
    assert names.isdisjoint(forbidden)


def test_brain_policy_roundtrips_through_immutable_genome() -> None:
    policy = AuraBrainPolicy(min_opportunity_confidence=0.72)
    genome = policy.to_genome()
    restored = AuraBrainPolicy.from_genome(genome)
    assert restored == policy


def test_brain_policy_blocks_low_confidence_or_excess_disagreement() -> None:
    gate = BrainPolicyGate(
        AuraBrainPolicy(
            min_opportunity_confidence=0.7,
            max_deliberation_disagreement=0.4,
        )
    )
    assert not gate.evaluate(
        round_result=_round(), memo=_memo(0.6), deliberation=_deliberation(0.2)
    ).allowed
    assert not gate.evaluate(
        round_result=_round(), memo=_memo(0.8), deliberation=_deliberation(0.6)
    ).allowed
    assert gate.evaluate(
        round_result=_round(), memo=_memo(0.8), deliberation=_deliberation(0.2)
    ).allowed
