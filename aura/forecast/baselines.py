from __future__ import annotations

import math
from itertools import pairwise
from statistics import pstdev

from aura.domain.models import NormalizedCandle
from aura.forecast.ensemble import ForecastDistribution
from aura.forecast.providers import ForecastProvider


def _log_returns(history: tuple[NormalizedCandle, ...], *, window: int) -> list[float]:
    closes = [float(item.close) for item in history[-(window + 1) :]]
    if len(closes) < 3:
        raise ValueError("baseline forecast requires at least three closed candles")
    return [math.log(current / previous) for previous, current in pairwise(closes)]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _distribution(
    *,
    model_key: str,
    symbol: str,
    history: tuple[NormalizedCandle, ...],
    horizon_steps: int,
    projected_log_return: float,
    dispersion_returns: list[float],
    calibration_score: float,
    reliability_score: float,
) -> ForecastDistribution:
    latest = history[-1]
    duration = latest.close_time - latest.open_time
    if duration.total_seconds() <= 0:
        raise ValueError("forecast candle duration must be positive")
    current = float(latest.close)
    median = current * math.exp(_clamp(projected_log_return, -0.5, 0.5))
    sigma = pstdev(dispersion_returns) if len(dispersion_returns) > 1 else 0.0
    horizon_sigma = sigma * math.sqrt(horizon_steps)
    quantile_distance = 1.2815515655446004 * horizon_sigma
    q10 = median * math.exp(-quantile_distance)
    q90 = median * math.exp(quantile_distance)
    return ForecastDistribution(
        model_key=model_key,
        symbol=symbol,
        horizon_steps=horizon_steps,
        generated_at=latest.close_time,
        target_timestamp=latest.close_time + duration * horizon_steps,
        point_forecast=median,
        q10=q10,
        q50=median,
        q90=q90,
        calibration_score=calibration_score,
        reliability_score=reliability_score,
    )


class DriftBaselineForecastProvider(ForecastProvider):
    """Causal rolling log-return baseline; it makes no pretrained-model claim."""

    model_key = "baseline:rolling-drift:v1"

    def __init__(
        self,
        *,
        window: int = 30,
        calibration_score: float = 0.5,
        reliability_score: float = 0.5,
    ) -> None:
        if window < 2:
            raise ValueError("drift window must be at least two")
        if not 0 <= calibration_score <= 1 or not 0 <= reliability_score <= 1:
            raise ValueError("baseline trust scores must be between zero and one")
        self.window = window
        self.calibration_score = calibration_score
        self.reliability_score = reliability_score

    async def forecast(
        self,
        *,
        symbol: str,
        history: tuple[NormalizedCandle, ...],
        horizon_steps: int,
        as_of,
    ) -> ForecastDistribution:
        returns = _log_returns(history, window=self.window)
        average_return = sum(returns) / len(returns)
        projected = _clamp(average_return, -0.02, 0.02) * horizon_steps
        return _distribution(
            model_key=self.model_key,
            symbol=symbol,
            history=history,
            horizon_steps=horizon_steps,
            projected_log_return=projected,
            dispersion_returns=returns,
            calibration_score=self.calibration_score,
            reliability_score=self.reliability_score,
        )


class EmaTrendBaselineForecastProvider(ForecastProvider):
    """Causal EMA-spread extrapolation used as a second independent baseline."""

    model_key = "baseline:ema-trend:v1"

    def __init__(
        self,
        *,
        fast_period: int = 8,
        slow_period: int = 21,
        calibration_score: float = 0.5,
        reliability_score: float = 0.5,
    ) -> None:
        if fast_period <= 0 or slow_period <= fast_period:
            raise ValueError("EMA baseline requires 0 < fast_period < slow_period")
        if not 0 <= calibration_score <= 1 or not 0 <= reliability_score <= 1:
            raise ValueError("baseline trust scores must be between zero and one")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.calibration_score = calibration_score
        self.reliability_score = reliability_score

    async def forecast(
        self,
        *,
        symbol: str,
        history: tuple[NormalizedCandle, ...],
        horizon_steps: int,
        as_of,
    ) -> ForecastDistribution:
        if len(history) < self.slow_period:
            raise ValueError(
                f"EMA baseline warmup incomplete: {len(history)}/{self.slow_period}"
            )
        closes = [float(item.close) for item in history]
        fast = _ema(closes, self.fast_period)
        slow = _ema(closes, self.slow_period)
        spread_per_bar = math.log(fast / slow) / (self.slow_period - self.fast_period)
        projected = _clamp(spread_per_bar, -0.02, 0.02) * horizon_steps
        returns = _log_returns(history, window=max(self.slow_period, 30))
        return _distribution(
            model_key=self.model_key,
            symbol=symbol,
            history=history,
            horizon_steps=horizon_steps,
            projected_log_return=projected,
            dispersion_returns=returns,
            calibration_score=self.calibration_score,
            reliability_score=self.reliability_score,
        )


def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        raise ValueError("EMA requires enough observations")
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    for item in values[period:]:
        value = alpha * item + (1.0 - alpha) * value
    return value
