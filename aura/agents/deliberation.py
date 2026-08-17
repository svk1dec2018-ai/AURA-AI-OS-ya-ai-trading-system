from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from aura.agents.models import AgentEvidence, AgentRound
from aura.domain.models import SignalIntent


class DeliberationCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: SignalIntent
    supporting_agents: tuple[str, ...]
    arguments: tuple[str, ...]
    weighted_strength: float = Field(ge=0.0)


class Counterfactual(BaseModel):
    model_config = ConfigDict(frozen=True)

    description: str
    affected_agents: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class DeliberationMemo:
    bull_case: DeliberationCase
    bear_case: DeliberationCase
    neutral_arguments: tuple[str, ...]
    counterfactuals: tuple[Counterfactual, ...]
    disagreement_ratio: float
    evidence_count: int


class AdversarialDeliberationEngine:
    """Evidence-grounded bull/bear/devil review before CEO synthesis.

    This is intentionally not hidden chain-of-thought. It preserves concise,
    auditable arguments already supplied by specialists and forces opposing
    evidence/counterfactual visibility, similar to a human investment committee.
    """

    def deliberate(self, round_result: AgentRound) -> DeliberationMemo:
        bull = [item for item in round_result.evidence if item.intent == SignalIntent.LONG]
        bear = [item for item in round_result.evidence if item.intent == SignalIntent.SHORT]
        neutral = [item for item in round_result.evidence if item.intent == SignalIntent.FLAT]

        bull_strength = self._strength(bull)
        bear_strength = self._strength(bear)
        directional_total = bull_strength + bear_strength
        disagreement = (
            min(bull_strength, bear_strength) / max(directional_total, 1e-12)
            if directional_total > 0
            else 0.0
        )

        counterfactuals: list[Counterfactual] = []
        all_evidence = tuple(round_result.evidence)
        high_risk = [item for item in all_evidence if item.risk_flags]
        if high_risk:
            counterfactuals.append(
                Counterfactual(
                    description="What if the flagged risk condition persists or worsens?",
                    affected_agents=tuple(sorted(item.agent_id for item in high_risk)),
                )
            )
        if bull and not bear:
            counterfactuals.append(
                Counterfactual(
                    description="What evidence would invalidate the unanimous bullish case?",
                    affected_agents=tuple(sorted(item.agent_id for item in bull)),
                )
            )
        if bear and not bull:
            counterfactuals.append(
                Counterfactual(
                    description="What evidence would invalidate the unanimous bearish case?",
                    affected_agents=tuple(sorted(item.agent_id for item in bear)),
                )
            )
        if round_result.failures:
            counterfactuals.append(
                Counterfactual(
                    description="Would the decision change if failed specialists returned opposing evidence?",
                    affected_agents=tuple(sorted(failure.agent_id for failure in round_result.failures)),
                )
            )

        return DeliberationMemo(
            bull_case=self._case(SignalIntent.LONG, bull),
            bear_case=self._case(SignalIntent.SHORT, bear),
            neutral_arguments=tuple(item.thesis for item in sorted(neutral, key=lambda x: x.agent_id)),
            counterfactuals=tuple(counterfactuals),
            disagreement_ratio=disagreement,
            evidence_count=len(all_evidence),
        )

    @staticmethod
    def _strength(evidence: list[AgentEvidence]) -> float:
        total = 0.0
        for item in evidence:
            source_trust = sum(source.trust_score for source in item.sources) / len(item.sources)
            total += item.confidence * source_trust
        return total

    def _case(self, intent: SignalIntent, evidence: list[AgentEvidence]) -> DeliberationCase:
        ordered = sorted(evidence, key=lambda item: (-item.confidence, item.agent_id))
        return DeliberationCase(
            intent=intent,
            supporting_agents=tuple(item.agent_id for item in ordered),
            arguments=tuple(item.thesis for item in ordered),
            weighted_strength=self._strength(evidence),
        )
