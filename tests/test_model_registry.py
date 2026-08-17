from aura.models.registry import (
    ModelDescriptor,
    ModelKind,
    ModelRegistry,
    ModelRequirement,
    ModelTask,
)


def test_router_prefers_reliable_calibrated_models_for_task() -> None:
    registry = ModelRegistry()
    registry.register(
        ModelDescriptor(
            provider_id="provider-a",
            model_id="reasoner-a",
            kind=ModelKind.REASONING_LLM,
            tasks=frozenset({ModelTask.MARKET_RESEARCH}),
            supports_tools=True,
            reliability_score=0.95,
            calibration_score=0.90,
            latency_score=0.60,
            cost_efficiency_score=0.50,
        )
    )
    registry.register(
        ModelDescriptor(
            provider_id="provider-b",
            model_id="fast-b",
            kind=ModelKind.REASONING_LLM,
            tasks=frozenset({ModelTask.MARKET_RESEARCH}),
            supports_tools=True,
            reliability_score=0.75,
            calibration_score=0.70,
            latency_score=0.95,
            cost_efficiency_score=0.95,
        )
    )

    routed = registry.route(
        ModelRequirement(
            task=ModelTask.MARKET_RESEARCH,
            require_tools=True,
            min_reliability=0.7,
        )
    )
    assert [item.descriptor.model_id for item in routed] == ["reasoner-a", "fast-b"]


def test_router_can_prefer_open_weight_without_bypassing_minimums() -> None:
    registry = ModelRegistry()
    registry.register(
        ModelDescriptor(
            provider_id="local",
            model_id="finance-open",
            kind=ModelKind.FINANCE_LLM,
            tasks=frozenset({ModelTask.NEWS_SENTIMENT}),
            local_or_open_weight=True,
            reliability_score=0.8,
            calibration_score=0.8,
        )
    )
    registry.register(
        ModelDescriptor(
            provider_id="remote",
            model_id="finance-api",
            kind=ModelKind.FINANCE_LLM,
            tasks=frozenset({ModelTask.NEWS_SENTIMENT}),
            reliability_score=0.8,
            calibration_score=0.8,
        )
    )

    routed = registry.route(
        ModelRequirement(
            task=ModelTask.NEWS_SENTIMENT,
            prefer_local_or_open_weight=True,
            min_reliability=0.75,
            min_calibration=0.75,
        )
    )
    assert routed[0].descriptor.model_id == "finance-open"


def test_research_only_model_can_be_excluded_from_runtime_route() -> None:
    registry = ModelRegistry()
    registry.register(
        ModelDescriptor(
            provider_id="research",
            model_id="rl-policy",
            kind=ModelKind.RL_POLICY,
            tasks=frozenset({ModelTask.SIMULATION_POLICY}),
            research_only=True,
            reliability_score=0.9,
            calibration_score=0.9,
        )
    )

    assert registry.route(
        ModelRequirement(
            task=ModelTask.SIMULATION_POLICY,
            allow_research_only=False,
        )
    ) == ()
