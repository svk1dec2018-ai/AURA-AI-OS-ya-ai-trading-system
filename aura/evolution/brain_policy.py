from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from aura.agents.advisory_specialists import ExecutionQualitySpecialist
from aura.agents.deliberation import DeliberationMemo
from aura.agents.models import AgentRound, CEODecisionMemo
from aura.agents.reliability import AgentReliabilityTracker
from aura.agents.risk_policy import AgentRiskPolicy
from aura.agents.team import AuraAgentTeam, build_default_agent_team
from aura.evolution.core import StrategyGenome
from aura.knowledge.firewall import KnowledgeFirewall


class AuraBrainPolicy(BaseModel):
    """Evolvable *intelligence* policy; financial risk limits are intentionally absent."""

    model_config = ConfigDict(frozen=True)

    ceo_directional_margin: float = Field(default=0.15, ge=0.05, le=0.50)
    min_opportunity_confidence: float = Field(default=0.60, ge=0.40, le=0.95)
    max_deliberation_disagreement: float = Field(default=0.65, ge=0.15, le=0.95)
    max_failed_agent_fraction: float = Field(default=0.30, ge=0.0, le=0.60)
    max_execution_spread_bps: float = Field(default=50.0, ge=1.0, le=100.0)
    max_execution_slippage_bps: float = Field(default=25.0, ge=1.0, le=60.0)

    def to_genome(self, *, generation: int = 0) -> StrategyGenome:
        return StrategyGenome(
            family="aura_brain_policy",
            parameters={
                key: float(value)
                for key, value in self.model_dump(mode="python").items()
            },
            generation=generation,
        )

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> AuraBrainPolicy:
        if genome.family != "aura_brain_policy":
            raise ValueError("brain policy requires aura_brain_policy genome")
        return cls(**{key: float(value) for key, value in genome.parameters.items()})


class BrainPolicyGeneSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    low: Decimal
    high: Decimal


BRAIN_POLICY_GENE_SPACE = (
    BrainPolicyGeneSpec(
        name="ceo_directional_margin",
        low=Decimal("0.05"),
        high=Decimal("0.50"),
    ),
    BrainPolicyGeneSpec(
        name="min_opportunity_confidence",
        low=Decimal("0.40"),
        high=Decimal("0.95"),
    ),
    BrainPolicyGeneSpec(
        name="max_deliberation_disagreement",
        low=Decimal("0.15"),
        high=Decimal("0.95"),
    ),
    BrainPolicyGeneSpec(
        name="max_failed_agent_fraction",
        low=Decimal("0.00"),
        high=Decimal("0.60"),
    ),
    BrainPolicyGeneSpec(
        name="max_execution_spread_bps",
        low=Decimal("1.0"),
        high=Decimal("100.0"),
    ),
    BrainPolicyGeneSpec(
        name="max_execution_slippage_bps",
        low=Decimal("1.0"),
        high=Decimal("60.0"),
    ),
)


class BrainPolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

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
            return BrainPolicyDecision(allowed=False, reason="CEO quorum not met")
        if memo.confidence < self.policy.min_opportunity_confidence:
            return BrainPolicyDecision(
                allowed=False,
                reason="opportunity confidence below brain policy",
            )
        total_agents = len(round_result.evidence) + len(round_result.failures)
        if total_agents:
            failure_fraction = len(round_result.failures) / total_agents
            if failure_fraction > self.policy.max_failed_agent_fraction:
                return BrainPolicyDecision(
                    allowed=False,
                    reason="too many specialist failures",
                )
        if (
            deliberation is not None
            and deliberation.disagreement_ratio
            > self.policy.max_deliberation_disagreement
        ):
            return BrainPolicyDecision(
                allowed=False,
                reason="bull/bear disagreement above brain policy",
            )
        return BrainPolicyDecision(allowed=True, reason="brain policy passed")


def build_brain_policy_team(
    firewall: KnowledgeFirewall,
    policy: AuraBrainPolicy,
    *,
    timeout_seconds: float = 10.0,
    risk_policy: AgentRiskPolicy | None = None,
    min_top_of_book_notional: float = 0.0,
    reliability_tracker: AgentReliabilityTracker | None = None,
) -> AuraAgentTeam:
    """Build an evolvable brain without changing downstream financial authority.

    Venue-specific evidence policy and contextual reliability state may be supplied
    and are preserved across brain champion swaps. Financial RiskEngine settings
    are not part of this builder or the evolvable genome.
    """
    return build_default_agent_team(
        firewall,
        execution_quality_specialist=ExecutionQualitySpecialist(
            max_spread_bps=policy.max_execution_spread_bps,
            max_estimated_slippage_bps=policy.max_execution_slippage_bps,
            min_top_of_book_notional=min_top_of_book_notional,
        ),
        timeout_seconds=timeout_seconds,
        min_directional_margin=policy.ceo_directional_margin,
        risk_policy=risk_policy,
        reliability_tracker=reliability_tracker,
    )
