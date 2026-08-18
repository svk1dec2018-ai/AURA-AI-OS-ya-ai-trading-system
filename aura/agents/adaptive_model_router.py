from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from aura.agents.base import SpecialistAgent
from aura.agents.models import AgentContext, AgentEvidence, AgentRole
from aura.agents.providers import ReasoningProvider
from aura.agents.reliability import AgentReliabilityTracker, reliability_market_key


@dataclass(slots=True, frozen=True)
class ModelRouteDecision:
    provider: ReasoningProvider
    model_key: str
    role: AgentRole
    market: str
    regime: str
    samples: int
    posterior_reliability: float
    exploration_bonus: float
    score: float


class AdaptiveModelRouter:
    """Select AI models using contextual reliability plus bounded exploration.

    This is advisory model routing only. It cannot place orders, mutate risk
    limits, change live approvals, or bypass the CEO/RiskEngine chain.
    """

    def __init__(
        self,
        providers: tuple[ReasoningProvider, ...] | list[ReasoningProvider],
        reliability_tracker: AgentReliabilityTracker,
        *,
        exploration_strength: float = 0.12,
        exact_regime_blend_samples: int = 20,
    ) -> None:
        if not providers:
            raise ValueError("adaptive model router requires at least one provider")
        if exploration_strength < 0:
            raise ValueError("exploration_strength cannot be negative")
        if exact_regime_blend_samples <= 0:
            raise ValueError("exact_regime_blend_samples must be positive")
        model_keys = [self.model_key(provider) for provider in providers]
        if len(model_keys) != len(set(model_keys)):
            raise ValueError("adaptive model router provider/model pairs must be unique")
        self.providers = tuple(providers)
        self.reliability_tracker = reliability_tracker
        self.exploration_strength = exploration_strength
        self.exact_regime_blend_samples = exact_regime_blend_samples

    def rank(
        self,
        *,
        role: AgentRole,
        context: AgentContext,
    ) -> tuple[ModelRouteDecision, ...]:
        market = reliability_market_key(context)
        regime = self._regime_hint(context)
        broad = {
            self.model_key(provider): self.reliability_tracker.summarize_model_role(
                self.model_key(provider),
                role=role,
                market=market,
                regime=None,
            )
            for provider in self.providers
        }
        total_samples = sum(item.samples for item in broad.values())
        decisions: list[ModelRouteDecision] = []
        for provider in self.providers:
            key = self.model_key(provider)
            broad_summary = broad[key]
            reliability = broad_summary.posterior_reliability
            samples = broad_summary.samples
            if regime != "unknown":
                exact = self.reliability_tracker.summarize_model_role(
                    key,
                    role=role,
                    market=market,
                    regime=regime,
                )
                if exact.samples:
                    exact_weight = min(
                        1.0,
                        exact.samples / self.exact_regime_blend_samples,
                    )
                    reliability = (
                        exact.posterior_reliability * exact_weight
                        + broad_summary.posterior_reliability * (1.0 - exact_weight)
                    )
            exploration_bonus = self.exploration_strength * math.sqrt(
                math.log(total_samples + len(self.providers) + 1.0) / (samples + 1.0)
            )
            jitter = self._deterministic_jitter(
                correlation_id=context.correlation_id,
                role=role,
                model_key=key,
            )
            decisions.append(
                ModelRouteDecision(
                    provider=provider,
                    model_key=key,
                    role=role,
                    market=market,
                    regime=regime,
                    samples=samples,
                    posterior_reliability=reliability,
                    exploration_bonus=exploration_bonus,
                    score=reliability + exploration_bonus + jitter,
                )
            )
        decisions.sort(key=lambda item: (-item.score, item.model_key))
        return tuple(decisions)

    def select(
        self,
        *,
        role: AgentRole,
        context: AgentContext,
        opinion_slot: int = 0,
    ) -> ModelRouteDecision:
        if opinion_slot < 0:
            raise ValueError("opinion_slot cannot be negative")
        ranked = self.rank(role=role, context=context)
        return ranked[opinion_slot % len(ranked)]

    @staticmethod
    def model_key(provider: ReasoningProvider) -> str:
        return f"{provider.provider_id}:{provider.model_id}"

    @staticmethod
    def _regime_hint(context: AgentContext) -> str:
        raw = context.metadata.get("regime")
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
        return "unknown"

    @staticmethod
    def _deterministic_jitter(
        *,
        correlation_id: str,
        role: AgentRole,
        model_key: str,
    ) -> float:
        payload = f"{correlation_id}|{role.value}|{model_key}".encode()
        digest = hashlib.sha256(payload).digest()
        integer = int.from_bytes(digest[:4], "big")
        return integer / (2**32 - 1) * 1e-6


class RoutedProviderBackedSpecialist(SpecialistAgent):
    """One stable specialist identity whose underlying AI model is routed per call."""

    def __init__(
        self,
        *,
        router: AdaptiveModelRouter,
        role: AgentRole,
        opinion_slot: int = 0,
        agent_id: str | None = None,
    ) -> None:
        if opinion_slot < 0:
            raise ValueError("opinion_slot cannot be negative")
        self.router = router
        self.role = role
        self.opinion_slot = opinion_slot
        self.agent_id = agent_id or (
            f"ai-council:router:{role.value}:opinion-{opinion_slot + 1}"
        )

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        route = self.router.select(
            role=self.role,
            context=context,
            opinion_slot=self.opinion_slot,
        )
        analysis = await route.provider.analyze(role=self.role, context=context)
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
                "provider_id": route.provider.provider_id,
                "model_id": route.provider.model_id,
                "router_market": route.market,
                "router_regime": route.regime,
                "router_samples": route.samples,
                "router_posterior_reliability": route.posterior_reliability,
                "router_exploration_bonus": route.exploration_bonus,
                "router_score": route.score,
                "router_opinion_slot": self.opinion_slot,
            },
            generated_at=context.candles[-1].close_time,
        )
