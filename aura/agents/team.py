from __future__ import annotations

from dataclasses import dataclass

from aura.agents.advisory_specialists import ExecutionQualitySpecialist
from aura.agents.base import SpecialistAgent
from aura.agents.external_specialists import (
    CrossMarketSpecialist,
    HigherTimeframeBiasSpecialist,
    KnowledgeMacroSentimentSpecialist,
    OptionsVolatilitySpecialist,
)
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.agents.specialists import (
    RegimeSpecialist,
    SmcIctStructureSpecialist,
    TechnicalSpecialist,
    VolumeVwapSpecialist,
)
from aura.knowledge.firewall import KnowledgeFirewall


@dataclass(slots=True, frozen=True)
class AuraAgentTeam:
    agents: tuple[SpecialistAgent, ...]
    orchestrator: MultiAgentOrchestrator
    ceo: CEOAggregator


def build_default_agent_team(
    knowledge_firewall: KnowledgeFirewall,
    *,
    extra_agents: tuple[SpecialistAgent, ...] = (),
    timeout_seconds: float = 10.0,
    min_directional_margin: float = 0.15,
) -> AuraAgentTeam:
    """Build AURA's default concurrent specialist team.

    `extra_agents` is the extension point for provider-backed AI models. They run
    in the same round as deterministic specialists, but neither they nor the CEO
    receive broker/risk authority.
    """

    base_agents: tuple[SpecialistAgent, ...] = (
        HigherTimeframeBiasSpecialist(),
        SmcIctStructureSpecialist(),
        TechnicalSpecialist(),
        VolumeVwapSpecialist(),
        OptionsVolatilitySpecialist(),
        KnowledgeMacroSentimentSpecialist(knowledge_firewall),
        CrossMarketSpecialist(),
        RegimeSpecialist(),
        ExecutionQualitySpecialist(),
    )
    agents = (*base_agents, *extra_agents)
    orchestrator = MultiAgentOrchestrator(list(agents), timeout_seconds=timeout_seconds)
    ceo = CEOAggregator(
        min_agents=5,
        min_distinct_roles=5,
        min_directional_margin=min_directional_margin,
    )
    return AuraAgentTeam(agents=agents, orchestrator=orchestrator, ceo=ceo)
