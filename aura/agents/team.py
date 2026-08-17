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
from aura.agents.forecast_specialist import ForecastEnsembleSpecialist
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.agents.risk_policy import AgentRiskPolicy
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
    risk_policy: AgentRiskPolicy


def build_default_agent_team(
    knowledge_firewall: KnowledgeFirewall,
    *,
    extra_agents: tuple[SpecialistAgent, ...] = (),
    timeout_seconds: float = 10.0,
    min_directional_margin: float = 0.15,
    risk_policy: AgentRiskPolicy | None = None,
) -> AuraAgentTeam:
    """Build AURA's default concurrent specialist team and evidence policy.

    `extra_agents` is the extension point for provider-backed AI models. They run
    in the same round as deterministic specialists, but neither they nor the CEO
    receive broker/risk authority. The returned evidence policy is part of the
    team contract and should be evaluated before any CEO candidate reaches the
    independent financial RiskEngine.
    """

    base_agents: tuple[SpecialistAgent, ...] = (
        HigherTimeframeBiasSpecialist(),
        SmcIctStructureSpecialist(),
        TechnicalSpecialist(),
        VolumeVwapSpecialist(),
        ForecastEnsembleSpecialist(),
        OptionsVolatilitySpecialist(),
        KnowledgeMacroSentimentSpecialist(knowledge_firewall),
        CrossMarketSpecialist(),
        RegimeSpecialist(),
        ExecutionQualitySpecialist(),
    )
    agents = (*base_agents, *extra_agents)
    orchestrator = MultiAgentOrchestrator(list(agents), timeout_seconds=timeout_seconds)
    ceo = CEOAggregator(
        min_agents=6,
        min_distinct_roles=6,
        min_directional_margin=min_directional_margin,
    )
    return AuraAgentTeam(
        agents=agents,
        orchestrator=orchestrator,
        ceo=ceo,
        risk_policy=risk_policy or AgentRiskPolicy(),
    )
