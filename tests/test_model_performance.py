from datetime import UTC, datetime, timedelta

import pytest

from aura.models.performance import ModelOutcomeObservation, ModelPerformanceTracker
from aura.models.registry import ModelDescriptor, ModelKind, ModelTask


def _obs(index: int, probability: float, outcome: bool, *, observed_day: int = 1):
    prediction = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
    return ModelOutcomeObservation(
        observation_id=f"o-{index}",
        model_key="provider:model",
        task=ModelTask.TIME_SERIES_FORECAST,
        market="XAUUSD",
        regime="trend",
        predicted_probability=probability,
        realized_outcome=outcome,
        prediction_time=prediction,
        outcome_observed_at=prediction + timedelta(days=observed_day),
        latency_ms=200,
    )


def test_tracker_learns_calibration_and_reliability() -> None:
    tracker = ModelPerformanceTracker()
    for index in range(20):
        tracker.record(_obs(index, 0.9 if index < 18 else 0.1, index < 18))

    summary = tracker.summarize(
        model_key="provider:model",
        task=ModelTask.TIME_SERIES_FORECAST,
        market="XAUUSD",
        regime="trend",
        as_of=datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert summary is not None
    assert summary.samples == 20
    assert summary.hit_rate == 1.0
    assert summary.calibration_score > 0.9
    assert summary.reliability_score > 0.9


def test_future_outcomes_do_not_influence_historical_model_routing() -> None:
    tracker = ModelPerformanceTracker()
    tracker.record(_obs(0, 0.9, True, observed_day=5))
    summary = tracker.summarize(
        model_key="provider:model",
        task=ModelTask.TIME_SERIES_FORECAST,
        market="XAUUSD",
        regime="trend",
        as_of=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert summary is None


def test_descriptor_is_adapted_only_after_minimum_sample_size() -> None:
    tracker = ModelPerformanceTracker()
    descriptor = ModelDescriptor(
        provider_id="provider",
        model_id="model",
        kind=ModelKind.TIME_SERIES_FOUNDATION,
        tasks=frozenset({ModelTask.TIME_SERIES_FORECAST}),
        reliability_score=0.5,
        calibration_score=0.5,
        latency_score=0.5,
    )
    for index in range(10):
        tracker.record(_obs(index, 0.9, True))

    unchanged = tracker.adapt_descriptor(
        descriptor,
        task=ModelTask.TIME_SERIES_FORECAST,
        market="XAUUSD",
        regime="trend",
        as_of=datetime(2026, 1, 10, tzinfo=UTC),
        min_samples=20,
    )
    assert unchanged == descriptor

    adapted = tracker.adapt_descriptor(
        descriptor,
        task=ModelTask.TIME_SERIES_FORECAST,
        market="XAUUSD",
        regime="trend",
        as_of=datetime(2026, 1, 10, tzinfo=UTC),
        min_samples=10,
    )
    assert adapted.reliability_score > descriptor.reliability_score
    assert adapted.calibration_score > descriptor.calibration_score


def test_outcome_before_prediction_is_rejected() -> None:
    tracker = ModelPerformanceTracker()
    prediction = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="after prediction"):
        tracker.record(
            ModelOutcomeObservation(
                observation_id="bad",
                model_key="provider:model",
                task=ModelTask.MARKET_RESEARCH,
                market="BTCUSDT",
                regime="chop",
                predicted_probability=0.5,
                realized_outcome=True,
                prediction_time=prediction,
                outcome_observed_at=prediction,
                latency_ms=1,
            )
        )
