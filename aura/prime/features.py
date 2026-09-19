from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field


class PrimeFeatureVector(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    sample_count: int = Field(ge=1)
    features: dict[str, float]


def extract_candle_features(
    candles: Sequence[dict[str, object]],
    *,
    symbol: str,
    timeframe: str,
) -> PrimeFeatureVector:
    """Extract deterministic closed-candle features from oldest->newest candles."""

    if len(candles) < 55:
        raise ValueError("Prime feature extraction requires at least 55 closed candles")
    if any(row.get("closed", True) is not True for row in candles):
        raise ValueError("Prime feature extraction accepts only closed candles")

    closes = [_positive(row.get("close"), "close") for row in candles]
    highs = [_positive(row.get("high"), "high") for row in candles]
    lows = [_positive(row.get("low"), "low") for row in candles]
    volumes = [_nonnegative(row.get("volume", 0), "volume") for row in candles]

    close = closes[-1]
    ema8 = _ema(closes, 8)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    rsi14 = _rsi(closes, 14)
    atr14 = _atr(highs, lows, closes, 14)
    volume_mean20 = sum(volumes[-20:]) / 20.0
    return_1 = math.log(closes[-1] / closes[-2])
    return_5 = math.log(closes[-1] / closes[-6])
    high20 = max(highs[-20:])
    low20 = min(lows[-20:])

    values = {
        "return_1": return_1,
        "return_5": return_5,
        "ema8_gap": (close - ema8) / close,
        "ema21_gap": (close - ema21) / close,
        "ema50_gap": (close - ema50) / close,
        "ema8_21_spread": (ema8 - ema21) / close,
        "ema21_50_spread": (ema21 - ema50) / close,
        "rsi14": rsi14 / 100.0,
        "atr14_pct": atr14 / close,
        "range20_position": _range_position(close, low20, high20),
        "volume_ratio20": volumes[-1] / volume_mean20 if volume_mean20 > 0 else 0.0,
    }
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError("Prime feature vector contains non-finite values")
    return PrimeFeatureVector(
        symbol=symbol,
        timeframe=timeframe,
        sample_count=len(candles),
        features=values,
    )


def _ema(values: Sequence[float], period: int) -> float:
    if len(values) < period:
        raise ValueError("insufficient values for EMA")
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result += alpha * (value - result)
    return result


def _rsi(values: Sequence[float], period: int) -> float:
    if len(values) <= period:
        raise ValueError("insufficient values for RSI")
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    recent = changes[-period:]
    gains = sum(max(change, 0.0) for change in recent) / period
    losses = sum(max(-change, 0.0) for change in recent) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> float:
    if len(closes) <= period:
        raise ValueError("insufficient values for ATR")
    true_ranges = []
    for index in range(1, len(closes)):
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    return sum(true_ranges[-period:]) / period


def _range_position(close: float, low: float, high: float) -> float:
    width = high - low
    if width <= 0:
        return 0.5
    return min(1.0, max(0.0, (close - low) / width))


def _positive(value: object, name: str) -> float:
    result = float(value)
    if result <= 0 or not math.isfinite(result):
        raise ValueError(f"{name} must be finite and positive")
    return result


def _nonnegative(value: object, name: str) -> float:
    result = float(value)
    if result < 0 or not math.isfinite(result):
        raise ValueError(f"{name} must be finite and non-negative")
    return result
