from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.models.registry import ModelDescriptor, ModelTask


class ModelOutcomeObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str = Field(min_length=1)
    model_key: str = Field(min_length=1)
    task: ModelTask
    market: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    predicted_probability: float = Field(ge=0.0, le=1.0)
    realized_outcome: bool
    prediction_time: datetime
    outcome_observed_at: datetime
    latency_ms: float = Field(ge=0.0)

    @field_validator("prediction_time", "outcome_observed_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("model performance timestamps must be timezone-aware")
        return value


@dataclass(slots=True, frozen=True)
class ModelPerformanceSummary:
    model_key: str
    task: ModelTask
    market: str
    regime: str
    samples: int
    hit_rate: float
    brier_score: float
    calibration_score: float
    reliability_score: float
    latency_score: float


class ModelPerformanceTracker:
    """Learn which models are dependable by task/market/regime from realized outcomes.

    Only outcomes whose observation timestamp is at or before the requested as-of
    time may influence a historical routing decision, preventing future model
    performance from leaking into past backtests.
    """

    def __init__(self) -> None:
        self._observations: dict[str, ModelOutcomeObservation] = {}

    def record(self, observation: ModelOutcomeObservation) -> None:
        if observation.outcome_observed_at <= observation.prediction_time:
            raise ValueError("realized outcome must be observed after prediction")
        existing = self._observations.get(observation.observation_id)
        if existing is not None and existing != observation:
            raise ValueError(f"observation_id collision: {observation.observation_id}")
        self._observations[observation.observation_id] = observation

    def summarize(
        self,
        *,
        model_key: str,
        task: ModelTask,
        market: str,
        regime: str,
        as_of: datetime,
    ) -> ModelPerformanceSummary | None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        items = [
            observation
            for observation in self._observations.values()
            if observation.model_key == model_key
            and observation.task == task
            and observation.market == market
            and observation.regime == regime
            and observation.outcome_observed_at <= as_of
        ]
        if not items:
            return None

        brier = sum(
            (item.predicted_probability - float(item.realized_outcome)) ** 2 for item in items
        ) / len(items)
        hit_rate = sum(
            (item.predicted_probability >= 0.5) == item.realized_outcome for item in items
        ) / len(items)
        average_latency = sum(item.latency_ms for item in items) / len(items)
        calibration = max(0.0, 1.0 - brier)
        reliability = max(0.0, min(1.0, 0.55 * hit_rate + 0.45 * calibration))
        latency_score = 1.0 / (1.0 + average_latency / 1000.0)
        return ModelPerformanceSummary(
            model_key=model_key,
            task=task,
            market=market,
            regime=regime,
            samples=len(items),
            hit_rate=hit_rate,
            brier_score=brier,
            calibration_score=calibration,
            reliability_score=reliability,
            latency_score=latency_score,
        )

    def adapt_descriptor(
        self,
        descriptor: ModelDescriptor,
        *,
        task: ModelTask,
        market: str,
        regime: str,
        as_of: datetime,
        min_samples: int = 20,
    ) -> ModelDescriptor:
        if min_samples <= 0:
            raise ValueError("min_samples must be positive")
        summary = self.summarize(
            model_key=descriptor.key,
            task=task,
            market=market,
            regime=regime,
            as_of=as_of,
        )
        if summary is None or summary.samples < min_samples:
            return descriptor
        return descriptor.model_copy(
            update={
                "reliability_score": summary.reliability_score,
                "calibration_score": summary.calibration_score,
                "latency_score": summary.latency_score,
            }
        )

    def leaderboard(
        self,
        *,
        task: ModelTask,
        market: str,
        regime: str,
        as_of: datetime,
        min_samples: int = 1,
    ) -> tuple[ModelPerformanceSummary, ...]:
        keys = defaultdict(bool)
        for observation in self._observations.values():
            if observation.task == task and observation.market == market and observation.regime == regime:
                keys[observation.model_key] = True
        summaries = [
            summary
            for model_key in keys
            if (
                summary := self.summarize(
                    model_key=model_key,
                    task=task,
                    market=market,
                    regime=regime,
                    as_of=as_of,
                )
            )
            is not None
            and summary.samples >= min_samples
        ]
        summaries.sort(
            key=lambda summary: (
                -summary.reliability_score,
                -summary.calibration_score,
                summary.model_key,
            )
        )
        return tuple(summaries)
