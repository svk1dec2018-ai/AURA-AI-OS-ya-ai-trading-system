from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from aura.agents.advisory_specialists import ExecutionQualitySpecialist
from aura.agents.deliberation import DeliberationMemo
from aura.agents.models import AgentRound, CEODecisionMemo
from aura.agents.team import AuraAgentTeam, build_default_agent_team
from aura.evolution.core import GeneKind, GeneSpec, StrategyGenome
from aura.knowledge.firewall import KnowledgeFirewall


class AuraBrainPolicy(BaseModel):
    """Evolvable advisory/selection policy; financial risk limits are excluded.

    AURA may research and paper-promote different evidence/decision thresholds,
    but this object has no position sizing, leverage, loss limit, kill-switch or
    broker permission fields. Those remain under the independent RiskEngine.
    """

    model_config = ConfigDict(frozen=True)

    ceo_directional_margin: float = Field(default=0.15, ge=0.05, le=0.50)
    min_opportunity_confidence: float = Field(default=0.60, ge=0.40, le=0.95)
    max_deliberation_disagreement: float = Field(default=0.65, ge=0.10, le=0.95)
    max_failed_agent_fraction: float = Field(default=0.30, ge=0.0, le=0.60)
    max_execution_spread_bps: float = Field(default=25.0, ge=1.0, le=100.0)
    max_execution_slippage_bps: float = Field(default=15.0, ge=0.5, le=50.0)

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> AuraBrainPolicy:
        if genome.family != "aura_brain_policy_v1":
            raise ValueError("genome is not an AURA brain policy candidate")
        return cls(**genome.parameters)

    def to_genome(self, *, generation: int = 0) -> StrategyGenome:
        return StrategyGenome(
            family="aura_brain_policy_v1",
            parameters=self.model_dump(),
            generation=generation,
        )


BRAIN_POLICY_GENE_SPACE: tuple[GeneSpec, ...] = (
    GeneSpec(
        name="ceo_directional_margin",
        kind=GeneKind.FLOAT,
        low=0.05,
        high=0.50,
        step=0.01,
        mutation_scale=0.08,
    ),
    GeneSpec(
        name="min_opportunity_confidence",
        kind=GeneKind.FLOAT,
        low=0.40,
        high=0.95,
        step=0.01,
        mutation_scale=0.08,
    ),
    GeneSpec(
        name="max_deliberation_disagreement",
        kind=GeneKind.FLOAT,
        low=0.10,
        high=0.95,
        step=0.01,
        mutation_scale=0.08,
    ),
    GeneSpec(
        name="max_failed_agent_fraction",
        kind=GeneKind.FLOAT,
        low=0.0,
        high=0.60,
        step=0.01,
        mutation_scale=0.08,
    ),
    GeneSpec(
        name="max_execution_spread_bps",
        kind=GeneKind.FLOAT,
        low=1.0,
        high=100.0,
        step=1.0,
        mutation_scale=0.10,
    ),
    GeneSpec(
        name="max_execution_slippage_bps",
        kind=GeneKind.FLOAT,
        low=0.5,
        high=50.0,
        step=0.5,
        mutation_scale=0.10,
    ),
)


@dataclass(slots=True, frozen=True)
class BrainPolicyDecision:
    allowed: bool
    reason: str


class BrainPolicyGate:
    def __init__(self, policy: AuraBrainPolicy) -> None:
        self.policy = policy

    def evaluate(
        self,
        *,
        round_result: AgentRound,
        memo: CEODecisionMemo,
        deliberation: DeliberationMemo | None,
    ) -> BrainPolicyDecision:
        if not memo.quorum_met:
            return BrainPolicyDecision(False, "CEO quorum not met")
        if memo.confidence < self.policy.min_opportunity_confidence:
            return BrainPolicyDecision(False, "opportunity confidence below brain policy")
        total_agents = len(round_result.evidence) + len(round_result.failures)
        if total_agents:
            failure_fraction = len(round_result.failures) / total_agents
            if failure_fraction > self.policy.max_failed_agent_fraction:
                return BrainPolicyDecision(False, "too many specialist failures")
        if (
            deliberation is not None
            and deliberation.disagreement_ratio
            > self.policy.max_deliberation_disagreement
        ):
            return BrainPolicyDecision(False, "bull/bear disagreement above brain policy")
        return BrainPolicyDecision(True, "brain policy passed")


def build_brain_policy_team(
    firewall: KnowledgeFirewall,
    policy: AuraBrainPolicy,
    *,
    timeout_seconds: float = 10.0,
) -> AuraAgentTeam:
    """Build a candidate AURA brain without touching the independent RiskEngine."""
    return build_default_agent_team(
        firewall,
        execution_quality_specialist=ExecutionQualitySpecialist(
            max_spread_bps=policy.max_execution_spread_bps,
            max_estimated_slippage_bps=policy.max_execution_slippage_bps,
            min_top_of_book_notional=0.0,
        ),
        timeout_seconds=timeout_seconds,
        min_directional_margin=policy.ceo_directional_margin,
    )
