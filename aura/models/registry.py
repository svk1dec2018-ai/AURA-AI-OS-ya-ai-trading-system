from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ModelKind(str, Enum):
    REASONING_LLM = "reasoning_llm"
    FINANCE_LLM = "finance_llm"
    TIME_SERIES_FOUNDATION = "time_series_foundation"
    TABULAR_ML = "tabular_ml"
    MULTIMODAL = "multimodal"
    RL_POLICY = "rl_policy"


class ModelTask(str, Enum):
    MARKET_RESEARCH = "market_research"
    NEWS_SENTIMENT = "news_sentiment"
    FUNDAMENTAL_ANALYSIS = "fundamental_analysis"
    TECHNICAL_REASONING = "technical_reasoning"
    TIME_SERIES_FORECAST = "time_series_forecast"
    OPTIONS_REASONING = "options_reasoning"
    CROSS_MARKET_REASONING = "cross_market_reasoning"
    STRATEGY_RESEARCH = "strategy_research"
    STRATEGY_CRITIQUE = "strategy_critique"
    REPORT_SYNTHESIS = "report_synthesis"
    SIMULATION_POLICY = "simulation_policy"


class ModelDescriptor(BaseModel):
    """Provider-neutral model metadata used by AURA's cognitive router.

    Scores are operational measurements from AURA's own evaluation harness, not
    vendor marketing claims. They may be refreshed over time without changing
    the financial authority chain.
    """

    model_config = ConfigDict(frozen=True)

    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    kind: ModelKind
    tasks: frozenset[ModelTask]
    enabled: bool = True
    local_or_open_weight: bool = False
    supports_tools: bool = False
    supports_structured_output: bool = True
    supports_images: bool = False
    reliability_score: float = Field(default=0.5, ge=0.0, le=1.0)
    calibration_score: float = Field(default=0.5, ge=0.0, le=1.0)
    latency_score: float = Field(default=0.5, ge=0.0, le=1.0)
    cost_efficiency_score: float = Field(default=0.5, ge=0.0, le=1.0)
    research_only: bool = False

    @property
    def key(self) -> str:
        return f"{self.provider_id}:{self.model_id}"


class ModelRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: ModelTask
    require_tools: bool = False
    require_structured_output: bool = True
    require_images: bool = False
    allow_research_only: bool = True
    prefer_local_or_open_weight: bool = False
    min_reliability: float = Field(default=0.0, ge=0.0, le=1.0)
    min_calibration: float = Field(default=0.0, ge=0.0, le=1.0)


@dataclass(slots=True, frozen=True)
class RoutedModel:
    descriptor: ModelDescriptor
    score: float


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelDescriptor] = {}

    def register(self, descriptor: ModelDescriptor) -> None:
        existing = self._models.get(descriptor.key)
        if existing is not None and existing != descriptor:
            raise ValueError(f"model registration collision: {descriptor.key}")
        self._models[descriptor.key] = descriptor

    def unregister(self, model_key: str) -> None:
        self._models.pop(model_key, None)

    def all(self) -> tuple[ModelDescriptor, ...]:
        return tuple(self._models[key] for key in sorted(self._models))

    def route(
        self,
        requirement: ModelRequirement,
        *,
        top_k: int = 3,
    ) -> tuple[RoutedModel, ...]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        candidates: list[RoutedModel] = []
        for model in self._models.values():
            if not self._eligible(model, requirement):
                continue
            score = self._score(model, requirement)
            candidates.append(RoutedModel(descriptor=model, score=score))

        candidates.sort(key=lambda item: (-item.score, item.descriptor.key))
        return tuple(candidates[:top_k])

    @staticmethod
    def _eligible(model: ModelDescriptor, requirement: ModelRequirement) -> bool:
        if not model.enabled or requirement.task not in model.tasks:
            return False
        if requirement.require_tools and not model.supports_tools:
            return False
        if requirement.require_structured_output and not model.supports_structured_output:
            return False
        if requirement.require_images and not model.supports_images:
            return False
        if not requirement.allow_research_only and model.research_only:
            return False
        if model.reliability_score < requirement.min_reliability:
            return False
        if model.calibration_score < requirement.min_calibration:
            return False
        return True

    @staticmethod
    def _score(model: ModelDescriptor, requirement: ModelRequirement) -> float:
        # Reliability/calibration dominate; speed/cost are tie-breakers. AURA's
        # own measured scores should populate these fields in production.
        score = (
            0.38 * model.reliability_score
            + 0.32 * model.calibration_score
            + 0.18 * model.latency_score
            + 0.12 * model.cost_efficiency_score
        )
        if requirement.prefer_local_or_open_weight and model.local_or_open_weight:
            score += 0.05
        return min(score, 1.0)
