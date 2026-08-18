from __future__ import annotations

import os
from dataclasses import dataclass

from aura.agents.base import SpecialistAgent
from aura.agents.models import AgentRole
from aura.agents.ollama_provider import OllamaReasoningProvider, build_ollama_providers_from_env
from aura.agents.providers import ProviderBackedSpecialist

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

    def __post_init__(self) -> None:
        if not self.roles:
            raise ValueError("AI council requires at least one role")
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("AI council roles must be unique")
        if not 1 <= self.opinions_per_role <= 3:
            raise ValueError("opinions_per_role must be between 1 and 3")


def build_ollama_ai_council(
    providers: tuple[OllamaReasoningProvider, ...] | list[OllamaReasoningProvider],
    *,
    config: AICouncilConfig | None = None,
) -> tuple[SpecialistAgent, ...]:
    """Map multiple local AI models across independent AURA specialist mandates.

    Each AI specialist receives the same point-in-time market context but a
    different mandate. Multiple opinions per role are allowed, but execution and
    risk authority remain outside the AI council.
    """

    if not providers:
        return ()
    effective = config or AICouncilConfig()
    models = tuple(providers)
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


def build_ollama_ai_council_from_env() -> tuple[SpecialistAgent, ...]:
    providers = build_ollama_providers_from_env()
    if not providers:
        return ()
    roles = _roles_from_env(os.getenv("AURA_AI_ROLES", ""))
    opinions = int(os.getenv("AURA_AI_OPINIONS_PER_ROLE", "1"))
    return build_ollama_ai_council(
        providers,
        config=AICouncilConfig(
            roles=roles or _DEFAULT_ROLES,
            opinions_per_role=opinions,
        ),
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
