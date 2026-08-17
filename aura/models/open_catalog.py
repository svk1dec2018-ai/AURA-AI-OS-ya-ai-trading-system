from __future__ import annotations

from aura.models.registry import ModelDescriptor, ModelKind, ModelRegistry, ModelTask


def register_researched_open_models(registry: ModelRegistry) -> None:
    """Register open/public model families studied for AURA.

    Initial quality scores are deliberately neutral. They must be replaced by
    AURA's own paper/shadow evaluation through ModelPerformanceTracker before
    routing decisions rely on them.
    """

    descriptors = (
        ModelDescriptor(
            provider_id="amazon-science",
            model_id="chronos-2",
            kind=ModelKind.TIME_SERIES_FOUNDATION,
            tasks=frozenset({ModelTask.TIME_SERIES_FORECAST}),
            local_or_open_weight=True,
            reliability_score=0.5,
            calibration_score=0.5,
            latency_score=0.5,
            cost_efficiency_score=0.7,
            research_only=True,
        ),
        ModelDescriptor(
            provider_id="google-research",
            model_id="timesfm-2.5",
            kind=ModelKind.TIME_SERIES_FOUNDATION,
            tasks=frozenset({ModelTask.TIME_SERIES_FORECAST}),
            local_or_open_weight=True,
            reliability_score=0.5,
            calibration_score=0.5,
            latency_score=0.5,
            cost_efficiency_score=0.7,
            research_only=True,
        ),
        ModelDescriptor(
            provider_id="salesforce-ai-research",
            model_id="moirai-moe-1.0-r",
            kind=ModelKind.TIME_SERIES_FOUNDATION,
            tasks=frozenset({ModelTask.TIME_SERIES_FORECAST}),
            local_or_open_weight=True,
            reliability_score=0.5,
            calibration_score=0.5,
            latency_score=0.4,
            cost_efficiency_score=0.6,
            research_only=True,
        ),
        ModelDescriptor(
            provider_id="ai4finance",
            model_id="fingpt",
            kind=ModelKind.FINANCE_LLM,
            tasks=frozenset(
                {
                    ModelTask.NEWS_SENTIMENT,
                    ModelTask.FUNDAMENTAL_ANALYSIS,
                    ModelTask.MARKET_RESEARCH,
                }
            ),
            local_or_open_weight=True,
            reliability_score=0.5,
            calibration_score=0.5,
            latency_score=0.5,
            cost_efficiency_score=0.7,
            research_only=True,
        ),
    )
    for descriptor in descriptors:
        registry.register(descriptor)
