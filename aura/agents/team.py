from __future__ import annotations

import os
from dataclasses import dataclass

from aura.agents.advisory_specialists import ExecutionQualitySpecialist
from aura.agents.ai_council import build_ollama_ai_council_from_env
from aura.agents.base import SpecialistAgent
from aura.agents.external_specialists import (
    CrossMarketSpecialist,
    HigherTimeframeBiasSpecialist,
    KnowledgeMacroSentimentSpecialist,
    OptionsVolatilitySpecialist,
)
from aura.agents.forecast_specialist import ForecastEnsembleSpecialist
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.agents.registry import AgentRegistry
from aura.agents.reliability import AgentReliabilityTracker
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
    registry: AgentRegistry
    orchestrator: MultiAgentOrchestrator
    ceo: CEOAggregator
    risk_policy: AgentRiskPolicy


def build_default_agent_team(
    knowledge_firewall: KnowledgeFirewall,
    *,
    extra_agents: tuple[SpecialistAgent, ...] = (),
    execution_quality_specialist: SpecialistAgent | None = None,
    timeout_seconds: float = 10.0,
    min_directional_margin: float = 0.15,
    risk_policy: AgentRiskPolicy | None = None,
    include_env_ai: bool = True,
    reliability_tracker: AgentReliabilityTracker | None = None,
) -> AuraAgentTeam:
    """Build AURA's deterministic desk plus an optional local multi-AI council.

    When `AURA_OLLAMA_MODELS` is configured, provider-backed AI specialists are
    added automatically. The same learned reliability state drives both adaptive
    model routing and bounded CEO vote weighting, while execution authority stays
    in the downstream governed risk/execution path.
    """

    execution_agent = execution_quality_specialist or ExecutionQualitySpecialist()
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
        execution_agent,
    )
    env_ai_agents = (
        build_ollama_ai_council_from_env(reliability_tracker=reliability_tracker)
        if include_env_ai
        else ()
    )
    agents = (*base_agents, *env_ai_agents, *extra_agents)
    effective_timeout = timeout_seconds
    if env_ai_agents:
        effective_timeout = max(
            timeout_seconds,
            float(os.getenv("AURA_AI_AGENT_TIMEOUT_SECONDS", "240")),
        )
    orchestrator = MultiAgentOrchestrator(
        list(agents),
        timeout_seconds=effective_timeout,
    )
    ceo = CEOAggregator(
        min_agents=6,
        min_distinct_roles=6,
        min_directional_margin=min_directional_margin,
        reliability_tracker=reliability_tracker,
    )
    return AuraAgentTeam(
        agents=agents,
        registry=orchestrator.registry,
        orchestrator=orchestrator,
        ceo=ceo,
        risk_policy=risk_policy or AgentRiskPolicy(),
    )
