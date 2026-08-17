from __future__ import annotations

import asyncio
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
        agent_ids = [agent.agent_id for agent in agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise AgentConfigurationError("specialist agent_id values must be unique")
        self.agents = tuple(agents)
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
                evidence = await agent.analyze(context)
            if evidence.agent_id != agent.agent_id or evidence.role != agent.role:
                raise AgentConfigurationError(
                    f"agent {agent.agent_id} returned mismatched identity/role"
                )
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
    """Deterministic CEO evidence synthesis with quorum and disagreement checks.

    This component is deliberately advisory. It cannot size positions, call a
    broker, or bypass the independent RiskEngine. A future LLM CEO may explain
    the same evidence bundle, but authority boundaries must remain identical.
    """

    def __init__(
        self,
        *,
        min_agents: int = 3,
        min_distinct_roles: int = 3,
        min_directional_margin: float = 0.15,
        role_weights: dict[AgentRole, float] | None = None,
    ) -> None:
        if min_agents <= 0 or min_distinct_roles <= 0:
            raise ValueError("CEO quorum thresholds must be positive")
        if not 0 <= min_directional_margin <= 1:
            raise ValueError("min_directional_margin must be between 0 and 1")
        self.min_agents = min_agents
        self.min_distinct_roles = min_distinct_roles
        self.min_directional_margin = min_directional_margin
        self.role_weights = dict(role_weights or {})

    def synthesize(self, round_result: AgentRound) -> CEODecisionMemo:
        distinct_roles = {item.role for item in round_result.evidence}
        quorum_met = (
            len(round_result.evidence) >= self.min_agents
            and len(distinct_roles) >= self.min_distinct_roles
        )

        if not quorum_met:
            return CEODecisionMemo(
                correlation_id=round_result.correlation_id,
                intent=SignalIntent.FLAT,
                confidence=0.0,
                supporting_agents=(),
                opposing_agents=(),
                abstaining_agents=tuple(item.agent_id for item in round_result.evidence),
                risk_flags=self._risk_flags(round_result.evidence),
                rationale=(
                    f"quorum not met: {len(round_result.evidence)} evidence packets from "
                    f"{len(distinct_roles)} distinct roles"
                ),
                quorum_met=False,
            )

        scores: dict[SignalIntent, float] = defaultdict(float)
        directional_agents: dict[SignalIntent, list[str]] = defaultdict(list)
        neutral_agents: list[str] = []
        for item in round_result.evidence:
            source_trust = sum(source.trust_score for source in item.sources) / len(item.sources)
            role_weight = self.role_weights.get(item.role, 1.0)
            effective_score = item.confidence * source_trust * role_weight
            scores[item.intent] += effective_score
            if item.intent == SignalIntent.FLAT:
                neutral_agents.append(item.agent_id)
            else:
                directional_agents[item.intent].append(item.agent_id)

        long_score = scores[SignalIntent.LONG]
        short_score = scores[SignalIntent.SHORT]
        directional_total = long_score + short_score
        if directional_total <= 0:
            return CEODecisionMemo(
                correlation_id=round_result.correlation_id,
                intent=SignalIntent.FLAT,
                confidence=0.0,
                supporting_agents=(),
                opposing_agents=(),
                abstaining_agents=tuple(neutral_agents),
                risk_flags=self._risk_flags(round_result.evidence),
                rationale="specialists produced no directional evidence",
                quorum_met=True,
            )

        directional_margin = abs(long_score - short_score) / directional_total
        if directional_margin < self.min_directional_margin:
            return CEODecisionMemo(
                correlation_id=round_result.correlation_id,
                intent=SignalIntent.FLAT,
                confidence=directional_margin,
                supporting_agents=(),
                opposing_agents=tuple(
                    sorted(
                        directional_agents[SignalIntent.LONG]
                        + directional_agents[SignalIntent.SHORT]
                    )
                ),
                abstaining_agents=tuple(neutral_agents),
                risk_flags=self._risk_flags(round_result.evidence),
                rationale=(
                    f"directional disagreement too high: margin {directional_margin:.3f} "
                    f"below required {self.min_directional_margin:.3f}"
                ),
                quorum_met=True,
            )

        intent = SignalIntent.LONG if long_score > short_score else SignalIntent.SHORT
        opposing = SignalIntent.SHORT if intent == SignalIntent.LONG else SignalIntent.LONG
        return CEODecisionMemo(
            correlation_id=round_result.correlation_id,
            intent=intent,
            confidence=min(directional_margin, 1.0),
            supporting_agents=tuple(sorted(directional_agents[intent])),
            opposing_agents=tuple(sorted(directional_agents[opposing])),
            abstaining_agents=tuple(sorted(neutral_agents)),
            risk_flags=self._risk_flags(round_result.evidence),
            rationale=(
                f"weighted evidence favors {intent.value}: long={long_score:.3f}, "
                f"short={short_score:.3f}, margin={directional_margin:.3f}"
            ),
            quorum_met=True,
        )

    @staticmethod
    def _risk_flags(evidence: tuple[AgentEvidence, ...]) -> tuple[str, ...]:
        return tuple(sorted({flag for item in evidence for flag in item.risk_flags}))
