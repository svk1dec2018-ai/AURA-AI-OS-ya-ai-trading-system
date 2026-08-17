from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.models.performance import ModelPerformanceTracker
from aura.models.registry import (
    ModelDescriptor,
    ModelRegistry,
    ModelRequirement,
    ModelTask,
    RoutedModel,
)


class CognitiveRoutingContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: ModelTask
    market: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    as_of: datetime
    minimum_samples_for_adaptation: int = Field(default=20, gt=0)

    @field_validator("as_of")
    @classmethod
    def as_of_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("routing as_of must be timezone-aware")
        return value


@dataclass(slots=True, frozen=True)
class CognitiveRoutingDecision:
    context: CognitiveRoutingContext
    primary: RoutedModel
    challengers: tuple[RoutedModel, ...]
    evaluated_models: tuple[ModelDescriptor, ...]


class CognitiveModelRouter:
    """Route model work by task/market/regime using only point-in-time performance.

    The registry defines capability eligibility. The performance tracker adapts
    reliability/calibration/latency from realized paper/shadow outcomes known as
    of the decision time. One primary model may produce the production advisory
    answer while challengers run in shadow for continuous evaluation.
    """

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        performance: ModelPerformanceTracker,
    ) -> None:
        self.registry = registry
        self.performance = performance

    def route(
        self,
        context: CognitiveRoutingContext,
        requirement: ModelRequirement,
        *,
        challenger_count: int = 2,
    ) -> CognitiveRoutingDecision:
        if requirement.task != context.task:
            raise ValueError("routing context task must match model requirement task")
        if challenger_count < 0:
            raise ValueError("challenger_count cannot be negative")

        adapted_registry = ModelRegistry()
        adapted: list[ModelDescriptor] = []
        for descriptor in self.registry.all():
            updated = self.performance.adapt_descriptor(
                descriptor,
                task=context.task,
                market=context.market,
                regime=context.regime,
                as_of=context.as_of,
                min_samples=context.minimum_samples_for_adaptation,
            )
            adapted_registry.register(updated)
            adapted.append(updated)

        routed = adapted_registry.route(requirement, top_k=1 + challenger_count)
        if not routed:
            raise LookupError(
                f"no eligible model for {context.task.value} in {context.market}/{context.regime}"
            )
        return CognitiveRoutingDecision(
            context=context,
            primary=routed[0],
            challengers=tuple(routed[1:]),
            evaluated_models=tuple(adapted),
        )
