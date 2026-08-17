from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from aura.domain.models import NormalizedCandle
from aura.forecast.ensemble import (
    EnsembleForecast,
    ForecastDistribution,
    ProbabilisticForecastEnsemble,
)


class ForecastProvider(ABC):
    model_key: str

    @abstractmethod
    async def forecast(
        self,
        *,
        symbol: str,
        history: tuple[NormalizedCandle, ...],
        horizon_steps: int,
        as_of: datetime,
    ) -> ForecastDistribution:
        raise NotImplementedError


class ForecastProviderFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_key: str
    error_type: str
    message: str


@dataclass(slots=True, frozen=True)
class ForecastRound:
    forecasts: tuple[ForecastDistribution, ...]
    failures: tuple[ForecastProviderFailure, ...]
    ensemble: EnsembleForecast | None


class ConcurrentForecastService:
    """Run heterogeneous time-series models concurrently and ensemble survivors."""

    def __init__(
        self,
        providers: tuple[ForecastProvider, ...],
        *,
        timeout_seconds: float = 20.0,
        min_models_for_ensemble: int = 2,
        ensemble: ProbabilisticForecastEnsemble | None = None,
    ) -> None:
        if not providers:
            raise ValueError("at least one forecast provider is required")
        if timeout_seconds <= 0:
            raise ValueError("forecast timeout_seconds must be positive")
        if min_models_for_ensemble <= 0:
            raise ValueError("min_models_for_ensemble must be positive")
        keys = [provider.model_key for provider in providers]
        if len(keys) != len(set(keys)):
            raise ValueError("forecast provider model_key values must be unique")
        self.providers = providers
        self.timeout_seconds = timeout_seconds
        self.min_models_for_ensemble = min_models_for_ensemble
        self.ensemble_engine = ensemble or ProbabilisticForecastEnsemble()

    async def run(
        self,
        *,
        symbol: str,
        history: tuple[NormalizedCandle, ...],
        horizon_steps: int,
        as_of: datetime,
    ) -> ForecastRound:
        if not history:
            raise ValueError("forecast service requires candle history")
        if horizon_steps <= 0:
            raise ValueError("horizon_steps must be positive")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("forecast as_of must be timezone-aware")
        if any(candle.symbol != symbol for candle in history):
            raise ValueError("forecast history symbol mismatch")
        if any(not candle.closed or candle.close_time > as_of for candle in history):
            raise ValueError("forecast history must contain only closed point-in-time candles")

        results = await asyncio.gather(
            *(self._run_provider(provider, symbol, history, horizon_steps, as_of) for provider in self.providers)
        )
        forecasts: list[ForecastDistribution] = []
        failures: list[ForecastProviderFailure] = []
        for forecast, failure in results:
            if forecast is not None:
                forecasts.append(forecast)
            if failure is not None:
                failures.append(failure)
        forecasts.sort(key=lambda item: item.model_key)
        failures.sort(key=lambda item: item.model_key)

        ensemble: EnsembleForecast | None = None
        if len(forecasts) >= self.min_models_for_ensemble:
            ensemble = self.ensemble_engine.combine(
                forecasts,
                min_models=self.min_models_for_ensemble,
            )
        return ForecastRound(
            forecasts=tuple(forecasts),
            failures=tuple(failures),
            ensemble=ensemble,
        )

    async def _run_provider(
        self,
        provider: ForecastProvider,
        symbol: str,
        history: tuple[NormalizedCandle, ...],
        horizon_steps: int,
        as_of: datetime,
    ) -> tuple[ForecastDistribution | None, ForecastProviderFailure | None]:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                forecast = await provider.forecast(
                    symbol=symbol,
                    history=history,
                    horizon_steps=horizon_steps,
                    as_of=as_of,
                )
            if forecast.model_key != provider.model_key:
                raise ValueError("forecast provider returned mismatched model_key")
            if forecast.symbol != symbol or forecast.horizon_steps != horizon_steps:
                raise ValueError("forecast provider returned mismatched symbol/horizon")
            if forecast.generated_at > as_of:
                raise ValueError("forecast provider returned future-generated result")
            return forecast, None
        except TimeoutError:
            return None, ForecastProviderFailure(
                model_key=provider.model_key,
                error_type="timeout",
                message=f"forecast provider exceeded {self.timeout_seconds}s timeout",
            )
        except Exception as exc:  # noqa: BLE001 - provider isolation boundary
            return None, ForecastProviderFailure(
                model_key=provider.model_key,
                error_type=type(exc).__name__,
                message=str(exc),
            )
