from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ForecastDistribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_key: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    horizon_steps: int = Field(gt=0)
    generated_at: datetime
    target_timestamp: datetime
    point_forecast: float
    q10: float
    q50: float
    q90: float
    calibration_score: float = Field(ge=0.0, le=1.0)
    reliability_score: float = Field(ge=0.0, le=1.0)

    @field_validator("generated_at", "target_timestamp")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_distribution(self) -> ForecastDistribution:
        if self.target_timestamp <= self.generated_at:
            raise ValueError("forecast target must be after generation time")
        if not self.q10 <= self.q50 <= self.q90:
            raise ValueError("forecast quantiles must be monotonic")
        return self


@dataclass(slots=True, frozen=True)
class EnsembleForecast:
    symbol: str
    horizon_steps: int
    generated_at: datetime
    target_timestamp: datetime
    point_forecast: float
    q10: float
    q50: float
    q90: float
    disagreement_score: float
    contributing_models: tuple[str, ...]
    total_weight: float


class ProbabilisticForecastEnsemble:
    """Blend heterogeneous forecasting models using AURA-measured calibration.

    This is designed for adapters such as Chronos, TimesFM, Moirai/Moirai-MoE,
    Qlib models and future finance-specific forecasters. No model is trusted from
    its name alone; AURA weights only its own measured calibration/reliability.
    """

    def combine(
        self,
        forecasts: list[ForecastDistribution] | tuple[ForecastDistribution, ...],
        *,
        min_models: int = 2,
        min_total_weight: float = 0.5,
    ) -> EnsembleForecast:
        if min_models < 1:
            raise ValueError("min_models must be at least 1")
        if not forecasts:
            raise ValueError("forecast ensemble requires at least one model")

        symbols = {forecast.symbol for forecast in forecasts}
        horizons = {forecast.horizon_steps for forecast in forecasts}
        generated_times = {forecast.generated_at for forecast in forecasts}
        targets = {forecast.target_timestamp for forecast in forecasts}
        if len(symbols) != 1 or len(horizons) != 1 or len(generated_times) != 1 or len(targets) != 1:
            raise ValueError("ensemble forecasts must share symbol, horizon and timestamps")
        if len(forecasts) < min_models:
            raise ValueError(f"forecast ensemble requires at least {min_models} models")

        weights = [forecast.calibration_score * forecast.reliability_score for forecast in forecasts]
        total_weight = sum(weights)
        if total_weight < min_total_weight:
            raise ValueError("forecast ensemble total trusted weight is below threshold")

        def weighted(attribute: str) -> float:
            return sum(
                getattr(forecast, attribute) * weight
                for forecast, weight in zip(forecasts, weights, strict=True)
            ) / total_weight

        point = weighted("point_forecast")
        q10 = weighted("q10")
        q50 = weighted("q50")
        q90 = weighted("q90")
        weighted_abs_deviation = sum(
            abs(forecast.point_forecast - point) * weight
            for forecast, weight in zip(forecasts, weights, strict=True)
        ) / total_weight
        scale = max(abs(point), 1e-12)
        disagreement = min(weighted_abs_deviation / scale, 1.0)

        first = forecasts[0]
        return EnsembleForecast(
            symbol=first.symbol,
            horizon_steps=first.horizon_steps,
            generated_at=first.generated_at,
            target_timestamp=first.target_timestamp,
            point_forecast=point,
            q10=q10,
            q50=q50,
            q90=q90,
            disagreement_score=disagreement,
            contributing_models=tuple(sorted(forecast.model_key for forecast in forecasts)),
            total_weight=total_weight,
        )
