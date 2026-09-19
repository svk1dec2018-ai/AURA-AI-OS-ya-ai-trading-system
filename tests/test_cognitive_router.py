from datetime import UTC, datetime, timedelta

from aura.models.cognitive_router import CognitiveModelRouter, CognitiveRoutingContext
from aura.models.performance import ModelOutcomeObservation, ModelPerformanceTracker
from aura.models.registry import (
    ModelDescriptor,
    ModelKind,
    ModelRegistry,
    ModelRequirement,
    ModelTask,
)


def _descriptor(model_id: str) -> ModelDescriptor:
    return ModelDescriptor(
        provider_id="provider",
        model_id=model_id,
        kind=ModelKind.REASONING_LLM,
        tasks=frozenset({ModelTask.MARKET_RESEARCH}),
        supports_tools=True,
        reliability_score=0.5,
        calibration_score=0.5,
        latency_score=0.5,
    )


def _record_good_history(tracker: ModelPerformanceTracker, model_id: str) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(20):
        prediction = start + timedelta(minutes=index)
        tracker.record(
            ModelOutcomeObservation(
                observation_id=f"{model_id}-{index}",
                model_key=f"provider:{model_id}",
                task=ModelTask.MARKET_RESEARCH,
                market="XAUUSD",
                regime="trend",
                predicted_probability=0.9,
                realized_outcome=True,
                prediction_time=prediction,
                outcome_observed_at=prediction + timedelta(hours=1),
                latency_ms=100,
            )
        )


def test_router_promotes_model_with_good_regime_specific_paper_history() -> None:
    registry = ModelRegistry()
    registry.register(_descriptor("a"))
    registry.register(_descriptor("b"))
    performance = ModelPerformanceTracker()
    _record_good_history(performance, "b")
    router = CognitiveModelRouter(registry=registry, performance=performance)

    decision = router.route(
        CognitiveRoutingContext(
            task=ModelTask.MARKET_RESEARCH,
            market="XAUUSD",
            regime="trend",
            as_of=datetime(2026, 1, 3, tzinfo=UTC),
            minimum_samples_for_adaptation=20,
        ),
        ModelRequirement(
            task=ModelTask.MARKET_RESEARCH,
            require_tools=True,
        ),
        challenger_count=1,
    )
    assert decision.primary.descriptor.model_id == "b"
    assert decision.challengers[0].descriptor.model_id == "a"


def test_future_performance_cannot_reorder_past_route() -> None:
    registry = ModelRegistry()
    registry.register(_descriptor("a"))
    registry.register(_descriptor("b"))
    performance = ModelPerformanceTracker()
    _record_good_history(performance, "b")
    router = CognitiveModelRouter(registry=registry, performance=performance)

    decision = router.route(
        CognitiveRoutingContext(
            task=ModelTask.MARKET_RESEARCH,
            market="XAUUSD",
            regime="trend",
            as_of=datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
            minimum_samples_for_adaptation=20,
        ),
        ModelRequirement(task=ModelTask.MARKET_RESEARCH, require_tools=True),
        challenger_count=1,
    )
    assert decision.primary.descriptor.model_id == "a"
