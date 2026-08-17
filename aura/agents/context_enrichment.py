from __future__ import annotations

from dataclasses import asdict

from aura.agents.models import AgentContext
from aura.data.live_plane import LiveDataHub, LiveDataRequirement
from aura.forecast.ensemble import EnsembleForecast
from aura.memory.cognitive import CognitiveMemoryStore, MemoryKind
from aura.models.cognitive_router import CognitiveRoutingDecision


class CognitiveContextEnricher:
    """Merge point-in-time memory, live data, forecasts and model routing into context."""

    def __init__(
        self,
        *,
        memory: CognitiveMemoryStore,
        live_data: LiveDataHub,
    ) -> None:
        self.memory = memory
        self.live_data = live_data

    def enrich(
        self,
        context: AgentContext,
        *,
        memory_subject: str | None = None,
        memory_tags: frozenset[str] = frozenset(),
        memory_kinds: frozenset[MemoryKind] | None = None,
        memory_limit: int = 20,
        live_requirements: tuple[LiveDataRequirement, ...] = (),
        require_complete_live_data: bool = False,
        forecast: EnsembleForecast | None = None,
        routing: CognitiveRoutingDecision | None = None,
    ) -> AgentContext:
        memories = self.memory.retrieve(
            as_of=context.created_at,
            subject=memory_subject or context.symbol,
            tags=memory_tags,
            kinds=memory_kinds,
            limit=memory_limit,
        )
        live_snapshot = self.live_data.snapshot(
            as_of=context.created_at,
            requirements=live_requirements,
        )
        if require_complete_live_data and not live_snapshot.complete:
            missing = ", ".join(
                f"{requirement.domain.value}:{requirement.subject}"
                for requirement in live_snapshot.missing_requirements
            )
            raise ValueError(f"required live cognitive data missing or stale: {missing}")

        metadata = dict(context.metadata)
        metadata["cognitive_memory"] = [
            {
                "memory_id": retrieved.item.memory_id,
                "kind": retrieved.item.kind.value,
                "subject": retrieved.item.subject,
                "content": retrieved.item.content,
                "observed_at": retrieved.item.observed_at,
                "importance": retrieved.item.importance,
                "trust_score": retrieved.item.trust_score,
                "tags": tuple(sorted(retrieved.item.tags)),
                "metadata": retrieved.item.metadata,
                "relevance_score": retrieved.relevance_score,
            }
            for retrieved in memories
        ]
        metadata["live_data_snapshot"] = {
            "complete": live_snapshot.complete,
            "events": [event.model_dump(mode="python") for event in live_snapshot.events],
            "missing": [
                {
                    "domain": requirement.domain.value,
                    "subject": requirement.subject,
                    "max_age_seconds": requirement.max_age.total_seconds(),
                    "min_trust_score": requirement.min_trust_score,
                }
                for requirement in live_snapshot.missing_requirements
            ],
        }
        if forecast is not None:
            if forecast.symbol != context.symbol:
                raise ValueError("forecast symbol does not match cognitive context")
            if forecast.generated_at > context.created_at:
                raise ValueError("forecast was generated after cognitive decision time")
            metadata["forecast_ensemble"] = asdict(forecast)
        if routing is not None:
            if routing.context.as_of > context.created_at:
                raise ValueError("model routing used future performance context")
            metadata["model_routing"] = {
                "task": routing.context.task.value,
                "market": routing.context.market,
                "regime": routing.context.regime,
                "primary": routing.primary.descriptor.key,
                "primary_score": routing.primary.score,
                "challengers": [item.descriptor.key for item in routing.challengers],
            }

        return context.model_copy(update={"metadata": metadata})
