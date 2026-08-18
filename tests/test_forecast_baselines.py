from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.domain.models import NormalizedCandle
from aura.forecast.baselines import (
    DriftBaselineForecastProvider,
    EmaTrendBaselineForecastProvider,
)
from aura.forecast.providers import ConcurrentForecastService


def _history(count: int = 40) -> tuple[NormalizedCandle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = []
    for index in range(count):
        opened = start + timedelta(minutes=index)
        price = Decimal(100) + Decimal(index) / Decimal(10)
        candles.append(
            NormalizedCandle(
                symbol="BTC-USD",
                venue="TEST",
                timeframe="1m",
                open_time=opened,
                close_time=opened + timedelta(minutes=1),
                open=price,
                high=price + Decimal("0.1"),
                low=price - Decimal("0.1"),
                close=price,
                volume=Decimal(10),
            )
        )
    return tuple(candles)


@pytest.mark.asyncio
async def test_causal_baselines_form_conservative_two_model_ensemble() -> None:
    history = _history()
    service = ConcurrentForecastService(
        (
            DriftBaselineForecastProvider(),
            EmaTrendBaselineForecastProvider(),
        )
    )

    result = await service.run(
        symbol="BTC-USD",
        history=history,
        horizon_steps=5,
        as_of=history[-1].close_time,
    )

    assert result.failures == ()
    assert result.ensemble is not None
    assert result.ensemble.contributing_models == (
        "baseline:ema-trend:v1",
        "baseline:rolling-drift:v1",
    )
    assert result.ensemble.total_weight == pytest.approx(0.5)
    assert result.ensemble.q10 <= result.ensemble.q50 <= result.ensemble.q90
    assert result.ensemble.target_timestamp == history[-1].close_time + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_ema_baseline_abstains_through_provider_failure_until_warm() -> None:
    history = _history(10)
    service = ConcurrentForecastService(
        (
            DriftBaselineForecastProvider(),
            EmaTrendBaselineForecastProvider(),
        )
    )

    result = await service.run(
        symbol="BTC-USD",
        history=history,
        horizon_steps=2,
        as_of=history[-1].close_time,
    )

    assert result.ensemble is None
    assert [item.model_key for item in result.failures] == ["baseline:ema-trend:v1"]
