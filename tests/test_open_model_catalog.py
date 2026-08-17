from aura.models.open_catalog import register_researched_open_models
from aura.models.registry import ModelRegistry, ModelRequirement, ModelTask


def test_open_catalog_registers_forecast_and_finance_models_as_research_only() -> None:
    registry = ModelRegistry()
    register_researched_open_models(registry)
    keys = {model.key for model in registry.all()}
    assert "amazon-science:chronos-2" in keys
    assert "google-research:timesfm-2.5" in keys
    assert "salesforce-ai-research:moirai-moe-1.0-r" in keys
    assert "ai4finance:fingpt" in keys
    assert all(model.research_only for model in registry.all())


def test_open_forecasters_are_not_eligible_for_runtime_until_validated() -> None:
    registry = ModelRegistry()
    register_researched_open_models(registry)
    routed = registry.route(
        ModelRequirement(
            task=ModelTask.TIME_SERIES_FORECAST,
            allow_research_only=False,
        )
    )
    assert routed == ()
