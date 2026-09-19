from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.domain.models import NormalizedCandle
from aura.forecast.ensemble import ForecastDistribution
from aura.forecast.providers import ConcurrentForecastService, ForecastProvider


class StaticForecastProvider(ForecastProvider):
    def __init__(self, model_key: str, point: float, *, fail: bool = False) -> None:
        self.model_key = model_key
        self.point = point
        self.fail = fail

    async def forecast(self, *, symbol, history, horizon_steps, as_of):
        if self.fail:
            raise RuntimeError("model unavailable")
        return ForecastDistribution(
            model_key=self.model_key,
            symbol=symbol,
            horizon_steps=horizon_steps,
            generated_at=as_of,
            target_timestamp=as_of + timedelta(minutes=5 * horizon_steps),
            point_forecast=self.point,
            q10=self.point - 1,
            q50=self.point,
            q90=self.point + 1,
            calibration_score=0.9,
            reliability_score=0.9,
        )


def _history():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="XAUUSD",
        venue="TEST",
        timeframe="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(10),
        closed=True,
    )
    return (candle,)


@pytest.mark.asyncio
async def test_multiple_forecasters_run_and_create_calibrated_ensemble() -> None:
    history = _history()
    service = ConcurrentForecastService(
        (
            StaticForecastProvider("chronos-2", 104),
            StaticForecastProvider("timesfm-2.5", 105),
            StaticForecastProvider("moirai-moe", 103),
        ),
        min_models_for_ensemble=2,
    )
    result = await service.run(
        symbol="XAUUSD",
        history=history,
        horizon_steps=12,
        as_of=history[-1].close_time,
    )
    assert len(result.forecasts) == 3
    assert result.failures == ()
    assert result.ensemble is not None
    assert result.ensemble.point_forecast == pytest.approx(104.0)


@pytest.mark.asyncio
async def test_one_forecast_model_failure_does_not_cancel_surviving_ensemble() -> None:
    history = _history()
    service = ConcurrentForecastService(
        (
            StaticForecastProvider("chronos-2", 104),
            StaticForecastProvider("timesfm-2.5", 105, fail=True),
            StaticForecastProvider("moirai-moe", 103),
        ),
        min_models_for_ensemble=2,
    )
    result = await service.run(
        symbol="XAUUSD",
        history=history,
        horizon_steps=12,
        as_of=history[-1].close_time,
    )
    assert len(result.forecasts) == 2
    assert [failure.model_key for failure in result.failures] == ["timesfm-2.5"]
    assert result.ensemble is not None
