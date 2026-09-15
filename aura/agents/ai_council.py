from __future__ import annotations

import os
from dataclasses import dataclass

from aura.agents.adaptive_model_router import (
    AdaptiveModelRouter,
    RoutedProviderBackedSpecialist,
)
from aura.agents.base import SpecialistAgent
from aura.agents.models import AgentRole
from aura.agents.ollama_provider import build_ollama_providers_from_env
from aura.agents.openai_provider import build_openai_providers_from_env
from aura.agents.providers import ProviderBackedSpecialist, ReasoningProvider
from aura.agents.reliability import AgentReliabilityTracker

_DEFAULT_ROLES = (
    AgentRole.HTF_BIAS,
    AgentRole.SMC_ICT,
    AgentRole.TECHNICAL,
    AgentRole.VOLUME_VWAP,
    AgentRole.FORECAST,
    AgentRole.OPTIONS_VOLATILITY,
    AgentRole.MACRO_SENTIMENT,
    AgentRole.CROSS_MARKET,
    AgentRole.REGIME,
    AgentRole.EXECUTION_QUALITY,
)


@dataclass(slots=True, frozen=True)
class AICouncilConfig:
    roles: tuple[AgentRole, ...] = _DEFAULT_ROLES
    opinions_per_role: int = 1
    adaptive_routing: bool = True
    exploration_strength: float = 0.12

    def __post_init__(self) -> None:
        if not self.roles:
            raise ValueError("AI council requires at least one role")
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("AI council roles must be unique")
        if not 1 <= self.opinions_per_role <= 3:
            raise ValueError("opinions_per_role must be between 1 and 3")
        if self.exploration_strength < 0:
            raise ValueError("exploration_strength cannot be negative")


def build_ollama_ai_council(
    providers: tuple[ReasoningProvider, ...] | list[ReasoningProvider],
    *,
    config: AICouncilConfig | None = None,
    reliability_tracker: AgentReliabilityTracker | None = None,
) -> tuple[SpecialistAgent, ...]:
    """Build independent AI specialists with optional adaptive model routing.

    With a reliability tracker, each role chooses models from forward-observed
    performance using bounded exploration. Multiple opinion slots select different
    ranked models when possible. Without learned state the legacy deterministic
    round-robin mapping is preserved.
    """

    if not providers:
        return ()
    effective = config or AICouncilConfig()
    models = tuple(providers)
    if effective.adaptive_routing and reliability_tracker is not None:
        router = AdaptiveModelRouter(
            models,
            reliability_tracker,
            exploration_strength=effective.exploration_strength,
        )
        return tuple(
            RoutedProviderBackedSpecialist(
                router=router,
                role=role,
                opinion_slot=opinion_index,
            )
            for role in effective.roles
            for opinion_index in range(effective.opinions_per_role)
        )

    agents: list[SpecialistAgent] = []
    for role_index, role in enumerate(effective.roles):
        for opinion_index in range(effective.opinions_per_role):
            provider = models[(role_index + opinion_index) % len(models)]
            agents.append(
                ProviderBackedSpecialist(
                    provider=provider,
                    role=role,
                    agent_id=(
                        f"ai-council:{provider.provider_id}:{provider.model_id}:"
                        f"{role.value}:opinion-{opinion_index + 1}"
                    ),
                )
            )
    return tuple(agents)


def build_ai_council(
    providers: tuple[ReasoningProvider, ...] | list[ReasoningProvider],
    *,
    config: AICouncilConfig | None = None,
    reliability_tracker: AgentReliabilityTracker | None = None,
) -> tuple[SpecialistAgent, ...]:
    """Provider-neutral council builder retained behind the Ollama-compatible API."""

    return build_ollama_ai_council(
        providers,
        config=config,
        reliability_tracker=reliability_tracker,
    )


def build_ollama_ai_council_from_env(
    *,
    reliability_tracker: AgentReliabilityTracker | None = None,
) -> tuple[SpecialistAgent, ...]:
    providers = build_ollama_providers_from_env()
    if not providers:
        return ()
    roles = _roles_from_env(os.getenv("AURA_AI_ROLES", ""))
    opinions = int(os.getenv("AURA_AI_OPINIONS_PER_ROLE", "1"))
    exploration = float(os.getenv("AURA_AI_ROUTER_EXPLORATION", "0.12"))
    adaptive = os.getenv("AURA_AI_ADAPTIVE_ROUTING", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return build_ollama_ai_council(
        providers,
        config=AICouncilConfig(
            roles=roles or _DEFAULT_ROLES,
            opinions_per_role=opinions,
            adaptive_routing=adaptive,
            exploration_strength=exploration,
        ),
        reliability_tracker=reliability_tracker,
    )


def build_env_ai_council_from_env(
    *,
    reliability_tracker: AgentReliabilityTracker | None = None,
) -> tuple[SpecialistAgent, ...]:
    """Load local Ollama and optional OpenAI models into one advisory council."""

    providers: tuple[ReasoningProvider, ...] = (
        *build_ollama_providers_from_env(),
        *build_openai_providers_from_env(),
    )
    if not providers:
        return ()
    roles = _roles_from_env(os.getenv("AURA_AI_ROLES", ""))
    opinions = int(os.getenv("AURA_AI_OPINIONS_PER_ROLE", "1"))
    exploration = float(os.getenv("AURA_AI_ROUTER_EXPLORATION", "0.12"))
    adaptive = os.getenv("AURA_AI_ADAPTIVE_ROUTING", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return build_ai_council(
        providers,
        config=AICouncilConfig(
            roles=roles or _DEFAULT_ROLES,
            opinions_per_role=opinions,
            adaptive_routing=adaptive,
            exploration_strength=exploration,
        ),
        reliability_tracker=reliability_tracker,
    )


def _roles_from_env(value: str) -> tuple[AgentRole, ...]:
    if not value.strip():
        return ()
    roles: list[AgentRole] = []
    for raw in value.split(","):
        normalized = raw.strip().lower()
        if not normalized:
            continue
        try:
            role = AgentRole(normalized)
        except ValueError as exc:
            valid = ", ".join(item.value for item in AgentRole)
            raise ValueError(f"unknown AURA_AI_ROLES value {raw!r}; valid roles: {valid}") from exc
        if role not in roles:
            roles.append(role)
    return tuple(roles)
