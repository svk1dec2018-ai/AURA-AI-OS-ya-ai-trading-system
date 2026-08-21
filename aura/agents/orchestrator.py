from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime

from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentFailure,
    AgentRole,
    AgentRound,
    CEODecisionMemo,
    CEODecisionTrace,
    DecisionReasonCode,
    EvidenceContribution,
)
from aura.agents.registry import AgentRegistry
from aura.agents.reliability import (
    AgentReliabilityTracker,
    reliability_market_key,
    reliability_regime_key,
)
from aura.domain.models import SignalIntent


class AgentConfigurationError(ValueError):
    pass


class MultiAgentOrchestrator:
    """Run independent AURA specialists concurrently and preserve every result.

    Failures are isolated per specialist. The orchestrator never turns agent
    output into an order; it only creates an auditable evidence round for the CEO
    synthesis layer and the downstream governed decision pipeline.
    """

    def __init__(
        self,
        agents: list[SpecialistAgent],
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not agents:
            raise AgentConfigurationError("at least one specialist agent is required")
        if timeout_seconds <= 0:
            raise AgentConfigurationError("timeout_seconds must be positive")
        self.agents = tuple(agents)
        try:
            self.registry = AgentRegistry.from_agents(self.agents)
        except (TypeError, ValueError) as exc:
            raise AgentConfigurationError(str(exc)) from exc
        self.timeout_seconds = timeout_seconds

    async def run_round(self, context: AgentContext) -> AgentRound:
        started_at = datetime.now(UTC)
        tasks = [asyncio.create_task(self._run_agent(agent, context)) for agent in self.agents]
        results = await asyncio.gather(*tasks)

        evidence: list[AgentEvidence] = []
        failures: list[AgentFailure] = []
        for agent_evidence, failure in results:
            if agent_evidence is not None:
                evidence.append(agent_evidence)
            if failure is not None:
                failures.append(failure)

        evidence.sort(key=lambda item: (item.role.value, item.agent_id))
        failures.sort(key=lambda item: (item.role.value, item.agent_id))
        return AgentRound(
            correlation_id=context.correlation_id,
            evidence=tuple(evidence),
            failures=tuple(failures),
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    async def _run_agent(
        self,
        agent: SpecialistAgent,
        context: AgentContext,
    ) -> tuple[AgentEvidence | None, AgentFailure | None]:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                raw_evidence = await agent.analyze(context)
            evidence = self.registry.validate_evidence(agent, raw_evidence)
            return evidence, None
        except TimeoutError:
            return None, AgentFailure(
                agent_id=agent.agent_id,
                role=agent.role,
                error_type="timeout",
                message=f"specialist exceeded {self.timeout_seconds}s timeout",
            )
        except Exception as exc:  # noqa: BLE001 - agent isolation boundary must contain failures
            return None, AgentFailure(
                agent_id=agent.agent_id,
                role=agent.role,
                error_type=type(exc).__name__,
                message=str(exc),
            )


class CEOAggregator:
    """Deterministic CEO evidence synthesis with contextual reliability weighting.

    Learned reliability only scales advisory evidence inside strict bounded vote
    weights. It cannot size positions, call a broker, alter the RiskEngine, disable
    a kill switch or approve a strategy for live money.
    """

    def __init__(
        self,
        *,
        min_agents: int = 3,
        min_distinct_roles: int = 3,
        min_directional_margin: float = 0.15,
        role_weights: dict[AgentRole, float] | None = None,
        reliability_tracker: AgentReliabilityTracker | None = None,
    ) -> None:
        if min_agents <= 0 or min_distinct_roles <= 0:
            raise ValueError("CEO quorum thresholds must be positive")
        if not 0 <= min_directional_margin <= 1:
            raise ValueError("min_directional_margin must be between 0 and 1")
        if any(
            not isinstance(role, AgentRole)
            or not math.isfinite(weight)
            or weight <= 0
            for role, weight in (role_weights or {}).items()
        ):
            raise ValueError("CEO role weights must be finite positive values")
        self.min_agents = min_agents
        self.min_distinct_roles = min_distinct_roles
        self.min_directional_margin = min_directional_margin
        self.role_weights = dict(role_weights or {})
        self.reliability_tracker = reliability_tracker

    def synthesize(
        self,
        round_result: AgentRound,
        *,
        context: AgentContext | None = None,
    ) -> CEODecisionMemo:
        evidence = tuple(
            sorted(round_result.evidence, key=lambda item: (item.role.value, item.agent_id))
        )
        distinct_roles = {item.role for item in evidence}
        quorum_met = (
            len(evidence) >= self.min_agents
            and len(distinct_roles) >= self.min_distinct_roles
        )
        market = reliability_market_key(context) if context is not None else "unknown"
        regime = (
            reliability_regime_key(round_result, context)
            if context is not None
            else "unknown"
        )
        scores: dict[SignalIntent, float] = defaultdict(float)
        directional_agents: dict[SignalIntent, list[str]] = defaultdict(list)
        neutral_agents: list[str] = []
        reliability_weights: list[float] = []
        contributions: list[EvidenceContribution] = []
        for item in evidence:
            source_trust = sum(source.trust_score for source in item.sources) / len(item.sources)
            role_weight = self.role_weights.get(item.role, 1.0)
            reliability_weight = 1.0
            if self.reliability_tracker is not None and context is not None:
                reliability_weight = self.reliability_tracker.vote_weight(
                    item,
                    market=market,
                    regime=regime,
                )
            reliability_weights.append(reliability_weight)
            effective_score = (
                item.confidence
                * source_trust
                * role_weight
                * reliability_weight
            )
            contribution = EvidenceContribution(
                agent_id=item.agent_id,
                role=item.role,
                intent=item.intent,
                confidence=self._stable_float(item.confidence),
                thesis=item.thesis,
                source_trust=self._stable_float(source_trust),
                role_weight=self._stable_float(role_weight),
                reliability_weight=self._stable_float(reliability_weight),
                effective_score=self._stable_float(effective_score),
                source_ids=tuple(sorted(source.source_id for source in item.sources)),
                risk_flags=tuple(sorted(set(item.risk_flags))),
            )
            contributions.append(contribution)
            scores[item.intent] += effective_score
            if item.intent == SignalIntent.FLAT:
                neutral_agents.append(item.agent_id)
            else:
                directional_agents[item.intent].append(item.agent_id)

        long_score = scores[SignalIntent.LONG]
        short_score = scores[SignalIntent.SHORT]
        directional_total = long_score + short_score
        directional_margin = (
            abs(long_score - short_score) / directional_total
            if directional_total > 0
            else 0.0
        )
        risk_flags = self._risk_flags(evidence)
        failure_agents = tuple(
            sorted(failure.agent_id for failure in round_result.failures)
        )

        def decision(
            *,
            intent: SignalIntent,
            confidence: float,
            supporting_agents: tuple[str, ...],
            opposing_agents: tuple[str, ...],
            abstaining_agents: tuple[str, ...],
            rationale: str,
            reason_code: DecisionReasonCode,
            quorum: bool,
        ) -> CEODecisionMemo:
            return self._build_memo(
                round_result=round_result,
                market=market,
                regime=regime,
                contributions=tuple(contributions),
                distinct_role_count=len(distinct_roles),
                failure_agents=failure_agents,
                long_score=long_score,
                short_score=short_score,
                directional_margin=directional_margin,
                intent=intent,
                confidence=confidence,
                supporting_agents=supporting_agents,
                opposing_agents=opposing_agents,
                abstaining_agents=abstaining_agents,
                risk_flags=risk_flags,
                rationale=rationale,
                reason_code=reason_code,
                quorum_met=quorum,
            )

        if not quorum_met:
            return decision(
                intent=SignalIntent.FLAT,
                confidence=0.0,
                supporting_agents=(),
                opposing_agents=(),
                abstaining_agents=tuple(sorted(item.agent_id for item in evidence)),
                rationale=(
                    f"quorum not met: {len(evidence)} evidence packets from "
                    f"{len(distinct_roles)} distinct roles"
                ),
                reason_code=DecisionReasonCode.QUORUM_NOT_MET,
                quorum=False,
            )

        if directional_total <= 0:
            return decision(
                intent=SignalIntent.FLAT,
                confidence=0.0,
                supporting_agents=(),
                opposing_agents=(),
                abstaining_agents=tuple(sorted(neutral_agents)),
                rationale="specialists produced no directional evidence",
                reason_code=DecisionReasonCode.NO_DIRECTIONAL_EVIDENCE,
                quorum=True,
            )

        reliability_note = ""
        if self.reliability_tracker is not None and context is not None:
            average_weight = sum(reliability_weights) / len(reliability_weights)
            reliability_note = (
                f", market={market}, regime={regime}, "
                f"avg_reliability_weight={average_weight:.3f}"
            )
        if directional_margin < self.min_directional_margin:
            return decision(
                intent=SignalIntent.FLAT,
                confidence=directional_margin,
                supporting_agents=(),
                opposing_agents=tuple(
                    sorted(
                        directional_agents[SignalIntent.LONG]
                        + directional_agents[SignalIntent.SHORT]
                    )
                ),
                abstaining_agents=tuple(sorted(neutral_agents)),
                rationale=(
                    f"directional disagreement too high: margin {directional_margin:.3f} "
                    f"below required {self.min_directional_margin:.3f}"
                    f"{reliability_note}"
                ),
                reason_code=DecisionReasonCode.DIRECTIONAL_DISAGREEMENT,
                quorum=True,
            )

        intent = SignalIntent.LONG if long_score > short_score else SignalIntent.SHORT
        opposing = SignalIntent.SHORT if intent == SignalIntent.LONG else SignalIntent.LONG
        return decision(
            intent=intent,
            confidence=min(directional_margin, 1.0),
            supporting_agents=tuple(sorted(directional_agents[intent])),
            opposing_agents=tuple(sorted(directional_agents[opposing])),
            abstaining_agents=tuple(sorted(neutral_agents)),
            rationale=(
                f"weighted evidence favors {intent.value}: long={long_score:.3f}, "
                f"short={short_score:.3f}, margin={directional_margin:.3f}"
                f"{reliability_note}"
            ),
            reason_code=DecisionReasonCode.WEIGHTED_EVIDENCE,
            quorum=True,
        )

    def _build_memo(
        self,
        *,
        round_result: AgentRound,
        market: str,
        regime: str,
        contributions: tuple[EvidenceContribution, ...],
        distinct_role_count: int,
        failure_agents: tuple[str, ...],
        long_score: float,
        short_score: float,
        directional_margin: float,
        intent: SignalIntent,
        confidence: float,
        supporting_agents: tuple[str, ...],
        opposing_agents: tuple[str, ...],
        abstaining_agents: tuple[str, ...],
        risk_flags: tuple[str, ...],
        rationale: str,
        reason_code: DecisionReasonCode,
        quorum_met: bool,
    ) -> CEODecisionMemo:
        trace_inputs = {
            "correlation_id": round_result.correlation_id,
            "market": market,
            "regime": regime,
            "thresholds": {
                "min_agents": self.min_agents,
                "min_distinct_roles": self.min_distinct_roles,
                "min_directional_margin": self._stable_float(
                    self.min_directional_margin
                ),
            },
            "contributions": [
                item.model_dump(mode="json") for item in contributions
            ],
            "failure_agents": list(failure_agents),
        }
        evidence_fingerprint = self._fingerprint(trace_inputs)
        decision_payload = {
            "evidence_fingerprint": evidence_fingerprint,
            "intent": intent.value,
            "confidence": self._stable_float(confidence),
            "supporting_agents": list(supporting_agents),
            "opposing_agents": list(opposing_agents),
            "abstaining_agents": list(abstaining_agents),
            "risk_flags": list(risk_flags),
            "reason_code": reason_code.value,
            "quorum_met": quorum_met,
        }
        trace = CEODecisionTrace(
            correlation_id=round_result.correlation_id,
            evidence_fingerprint=evidence_fingerprint,
            decision_fingerprint=self._fingerprint(decision_payload),
            market=market,
            regime=regime,
            evidence_count=len(contributions),
            distinct_role_count=distinct_role_count,
            failure_agents=failure_agents,
            min_agents=self.min_agents,
            min_distinct_roles=self.min_distinct_roles,
            min_directional_margin=self._stable_float(self.min_directional_margin),
            long_score=self._stable_float(long_score),
            short_score=self._stable_float(short_score),
            directional_margin=self._stable_float(directional_margin),
            reason_code=reason_code,
            contributions=contributions,
        )
        return CEODecisionMemo(
            correlation_id=round_result.correlation_id,
            intent=intent,
            confidence=self._stable_float(confidence),
            supporting_agents=supporting_agents,
            opposing_agents=opposing_agents,
            abstaining_agents=abstaining_agents,
            risk_flags=risk_flags,
            rationale=rationale,
            quorum_met=quorum_met,
            decision_trace=trace,
            generated_at=round_result.completed_at,
        )

    @staticmethod
    def _stable_float(value: float) -> float:
        return round(float(value), 12)

    @staticmethod
    def _fingerprint(value: object) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _risk_flags(evidence: tuple[AgentEvidence, ...]) -> tuple[str, ...]:
        return tuple(sorted({flag for item in evidence for flag in item.risk_flags}))
