from datetime import UTC, datetime, timedelta

import pytest

from aura.forecast.ensemble import ForecastDistribution, ProbabilisticForecastEnsemble


def _forecast(model_key: str, point: float, calibration: float, reliability: float):
    generated = datetime(2026, 1, 1, tzinfo=UTC)
    return ForecastDistribution(
        model_key=model_key,
        symbol="XAUUSD",
        horizon_steps=12,
        generated_at=generated,
        target_timestamp=generated + timedelta(hours=1),
        point_forecast=point,
        q10=point - 5,
        q50=point,
        q90=point + 5,
        calibration_score=calibration,
        reliability_score=reliability,
    )


def test_ensemble_weights_models_by_measured_quality() -> None:
    forecasts = [
        _forecast("chronos-2", 2600, 0.95, 0.95),
        _forecast("timesfm-2.5", 2610, 0.90, 0.90),
        _forecast("moirai-moe", 2700, 0.30, 0.40),
    ]
    result = ProbabilisticForecastEnsemble().combine(forecasts, min_models=3)
    assert result.point_forecast < 2640
    assert result.q10 <= result.q50 <= result.q90
    assert result.contributing_models == ("chronos-2", "moirai-moe", "timesfm-2.5")
    assert 0 <= result.disagreement_score <= 1


def test_low_trust_ensemble_is_rejected() -> None:
    forecasts = [
        _forecast("a", 100, 0.1, 0.1),
        _forecast("b", 101, 0.1, 0.1),
    ]
    with pytest.raises(ValueError, match="trusted weight"):
        ProbabilisticForecastEnsemble().combine(forecasts, min_total_weight=0.5)


def test_quantile_crossing_is_rejected_at_model_boundary() -> None:
    generated = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="quantiles"):
        ForecastDistribution(
            model_key="bad",
            symbol="X",
            horizon_steps=1,
            generated_at=generated,
            target_timestamp=generated + timedelta(minutes=5),
            point_forecast=100,
            q10=105,
            q50=100,
            q90=110,
            calibration_score=1,
            reliability_score=1,
        )
