from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aura.agents.base import SpecialistAgent
from aura.agents.models import AgentContext, AgentEvidence, AgentRole, EvidenceSource
from aura.domain.models import SignalIntent


class ProviderAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    thesis: str = Field(min_length=1)
    risk_flags: tuple[str, ...] = ()
    sources: tuple[EvidenceSource, ...]
    features: dict[str, Any] = Field(default_factory=dict)


class ReasoningProvider(ABC):
    """Provider-neutral AI reasoning contract.

    Concrete adapters may call different models/providers, but credentials stay
    outside this interface and returned analysis must include auditable evidence
    sources. Providers never receive broker execution authority.
    """

    provider_id: str
    model_id: str

    @abstractmethod
    async def analyze(self, *, role: AgentRole, context: AgentContext) -> ProviderAnalysis:
        raise NotImplementedError


class ProviderBackedSpecialist(SpecialistAgent):
    """Wrap one AI provider/model as one specialist in the concurrent AURA team."""

    def __init__(
        self,
        *,
        provider: ReasoningProvider,
        role: AgentRole,
        agent_id: str | None = None,
        fallback_providers: tuple[ReasoningProvider, ...] | list[ReasoningProvider] = (),
    ) -> None:
        self.provider = provider
        self.role = role
        self.fallback_providers = tuple(
            item
            for item in fallback_providers
            if not (
                item.provider_id == provider.provider_id
                and item.model_id == provider.model_id
            )
        )
        self.agent_id = agent_id or f"{provider.provider_id}:{provider.model_id}:{role.value}"

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        providers = (self.provider, *self.fallback_providers)
        failures: list[str] = []
        selected: ReasoningProvider | None = None
        analysis: ProviderAnalysis | None = None
        for candidate in providers:
            try:
                analysis = await candidate.analyze(role=self.role, context=context)
                selected = candidate
                break
            except (RuntimeError, TimeoutError, OSError, ValueError) as exc:
                failures.append(
                    f"{candidate.provider_id}:{candidate.model_id}:{type(exc).__name__}"
                )
        if analysis is None or selected is None:
            raise RuntimeError(
                "all configured reasoning providers failed: " + ", ".join(failures)
            )
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=analysis.intent,
            confidence=analysis.confidence,
            thesis=analysis.thesis,
            risk_flags=analysis.risk_flags,
            sources=analysis.sources,
            features={
                **analysis.features,
                "provider_id": selected.provider_id,
                "model_id": selected.model_id,
                "fallback_attempts": len(failures),
                "fallback_failures": tuple(failures),
            },
            generated_at=context.candles[-1].close_time,
        )
