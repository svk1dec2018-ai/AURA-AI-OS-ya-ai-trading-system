from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any

from aura.domain.models import NormalizedCandle


@dataclass(frozen=True, slots=True)
class FeatureConfig:
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_period: int = 20
    bollinger_stddev: Decimal = Decimal("2")
    atr_period: int = 14
    supertrend_period: int = 10
    supertrend_multiplier: Decimal = Decimal("3")
    support_resistance_lookback: int = 20

    def __post_init__(self) -> None:
        positive_ints = (
            self.rsi_period,
            self.macd_fast,
            self.macd_slow,
            self.macd_signal,
            self.bollinger_period,
            self.atr_period,
            self.supertrend_period,
            self.support_resistance_lookback,
        )
        if any(value <= 0 for value in positive_ints):
            raise ValueError("feature periods must be positive")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("MACD fast period must be smaller than slow period")
        if self.bollinger_stddev <= 0 or self.supertrend_multiplier <= 0:
            raise ValueError("feature multipliers must be positive")


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    symbol: str
    venue: str
    timeframe: str
    as_of: datetime
    bars_used: int
    close: Decimal
    ema_8: Decimal | None
    ema_21: Decimal | None
    ema_50: Decimal | None
    ema_200: Decimal | None
    rsi_14: Decimal | None
    macd_line: Decimal | None
    macd_signal: Decimal | None
    macd_histogram: Decimal | None
    bollinger_mid: Decimal | None
    bollinger_upper: Decimal | None
    bollinger_lower: Decimal | None
    atr_14: Decimal | None
    supertrend: Decimal | None
    supertrend_direction: int | None
    vwap: Decimal | None
    obv: Decimal
    vpt: Decimal
    support: Decimal | None
    resistance: Decimal | None

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "as_of": self.as_of.isoformat(),
            "bars_used": self.bars_used,
            "close": str(self.close),
            "supertrend_direction": self.supertrend_direction,
        }
        for name in (
            "ema_8",
            "ema_21",
            "ema_50",
            "ema_200",
            "rsi_14",
            "macd_line",
            "macd_signal",
            "macd_histogram",
            "bollinger_mid",
            "bollinger_upper",
            "bollinger_lower",
            "atr_14",
            "supertrend",
            "vwap",
            "obv",
            "vpt",
            "support",
            "resistance",
        ):
            value = getattr(self, name)
            payload[name] = None if value is None else str(value)
        return payload


class UnifiedFeatureEngine:
    """Closed-candle, broker-neutral indicator calculations shared across AURA.

    The engine intentionally contains no trading authority. It only transforms a
    validated candle series into deterministic point-in-time features so scanner,
    research, backtest and paper paths can consume identical calculations.
    """

    def __init__(self, config: FeatureConfig | None = None) -> None:
        self.config = config or FeatureConfig()

    def compute(
        self,
        candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle],
        *,
        decision_time: datetime | None = None,
    ) -> FeatureSnapshot:
        series = tuple(candles)
        self._validate_series(series, decision_time=decision_time)
        closes = [candle.close for candle in series]

        ema8 = _latest(_ema_aligned(closes, 8))
        ema21 = _latest(_ema_aligned(closes, 21))
        ema50 = _latest(_ema_aligned(closes, 50))
        ema200 = _latest(_ema_aligned(closes, 200))
        rsi = _rsi_wilder(closes, self.config.rsi_period)
        macd_line, macd_signal, macd_histogram = _macd(
            closes,
            fast=self.config.macd_fast,
            slow=self.config.macd_slow,
            signal=self.config.macd_signal,
        )
        bollinger_mid, bollinger_upper, bollinger_lower = _bollinger(
            closes,
            period=self.config.bollinger_period,
            stddev=self.config.bollinger_stddev,
        )
        atr = _latest(_atr_aligned(series, self.config.atr_period))
        supertrend, supertrend_direction = _supertrend(
            series,
            period=self.config.supertrend_period,
            multiplier=self.config.supertrend_multiplier,
        )
        vwap = _vwap(series)
        obv = _obv(series)
        vpt = _vpt(series)
        support, resistance = _support_resistance(
            series,
            lookback=self.config.support_resistance_lookback,
        )
        latest = series[-1]
        return FeatureSnapshot(
            symbol=latest.symbol,
            venue=latest.venue,
            timeframe=latest.timeframe,
            as_of=latest.close_time,
            bars_used=len(series),
            close=latest.close,
            ema_8=ema8,
            ema_21=ema21,
            ema_50=ema50,
            ema_200=ema200,
            rsi_14=rsi,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            bollinger_mid=bollinger_mid,
            bollinger_upper=bollinger_upper,
            bollinger_lower=bollinger_lower,
            atr_14=atr,
            supertrend=supertrend,
            supertrend_direction=supertrend_direction,
            vwap=vwap,
            obv=obv,
            vpt=vpt,
            support=support,
            resistance=resistance,
        )

    @staticmethod
    def _validate_series(
        candles: tuple[NormalizedCandle, ...],
        *,
        decision_time: datetime | None,
    ) -> None:
        if not candles:
            raise ValueError("feature engine requires at least one candle")
        if any(not candle.closed for candle in candles):
            raise ValueError("feature engine accepts closed candles only")
        if len({candle.symbol for candle in candles}) != 1:
            raise ValueError("feature engine requires one symbol per series")
        if len({candle.venue for candle in candles}) != 1:
            raise ValueError("feature engine requires one venue per series")
        if len({candle.timeframe for candle in candles}) != 1:
            raise ValueError("feature engine requires one timeframe per series")
        if any(
            candles[index].open_time <= candles[index - 1].open_time
            for index in range(1, len(candles))
        ):
            raise ValueError("feature engine requires strictly increasing candles")
        if decision_time is not None:
            if decision_time.tzinfo is None or decision_time.utcoffset() is None:
                raise ValueError("decision_time must be timezone-aware")
            if any(candle.close_time > decision_time for candle in candles):
                raise ValueError("feature engine cannot use future candle data")


def _latest(values: list[Decimal | None]) -> Decimal | None:
    return values[-1] if values else None


def _ema_aligned(values: list[Decimal], period: int) -> list[Decimal | None]:
    aligned: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return aligned
    ema = sum(values[:period], Decimal(0)) / Decimal(period)
    aligned[period - 1] = ema
    alpha = Decimal(2) / Decimal(period + 1)
    for index in range(period, len(values)):
        ema = alpha * values[index] + (Decimal(1) - alpha) * ema
        aligned[index] = ema
    return aligned


def _rsi_wilder(values: list[Decimal], period: int) -> Decimal | None:
    if len(values) < period + 1:
        return None
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [max(-change, Decimal(0)) for change in changes]
    average_gain = sum(gains[:period], Decimal(0)) / Decimal(period)
    average_loss = sum(losses[:period], Decimal(0)) / Decimal(period)
    for index in range(period, len(changes)):
        average_gain = (
            average_gain * Decimal(period - 1) + gains[index]
        ) / Decimal(period)
        average_loss = (
            average_loss * Decimal(period - 1) + losses[index]
        ) / Decimal(period)
    if average_loss == 0:
        return Decimal(100) if average_gain > 0 else Decimal(50)
    relative_strength = average_gain / average_loss
    return Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength)


def _macd(
    values: list[Decimal],
    *,
    fast: int,
    slow: int,
    signal: int,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    fast_ema = _ema_aligned(values, fast)
    slow_ema = _ema_aligned(values, slow)
    macd_aligned: list[Decimal | None] = [None] * len(values)
    compact: list[Decimal] = []
    compact_indices: list[int] = []
    for index, (fast_value, slow_value) in enumerate(zip(fast_ema, slow_ema, strict=True)):
        if fast_value is None or slow_value is None:
            continue
        value = fast_value - slow_value
        macd_aligned[index] = value
        compact.append(value)
        compact_indices.append(index)
    macd_line = _latest(macd_aligned)
    if len(compact) < signal:
        return macd_line, None, None
    signal_compact = _ema_aligned(compact, signal)
    latest_signal = _latest(signal_compact)
    if macd_line is None or latest_signal is None:
        return macd_line, latest_signal, None
    return macd_line, latest_signal, macd_line - latest_signal


def _bollinger(
    values: list[Decimal],
    *,
    period: int,
    stddev: Decimal,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if len(values) < period:
        return None, None, None
    sample = values[-period:]
    middle = sum(sample, Decimal(0)) / Decimal(period)
    variance = sum(((value - middle) ** 2 for value in sample), Decimal(0)) / Decimal(period)
    with localcontext() as context:
        context.prec = 34
        deviation = variance.sqrt()
    width = deviation * stddev
    return middle, middle + width, middle - width


def _true_ranges(candles: tuple[NormalizedCandle, ...]) -> list[Decimal]:
    ranges: list[Decimal] = []
    for index, candle in enumerate(candles):
        if index == 0:
            ranges.append(candle.high - candle.low)
            continue
        previous_close = candles[index - 1].close
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return ranges


def _atr_aligned(
    candles: tuple[NormalizedCandle, ...],
    period: int,
) -> list[Decimal | None]:
    true_ranges = _true_ranges(candles)
    aligned: list[Decimal | None] = [None] * len(true_ranges)
    if len(true_ranges) < period:
        return aligned
    atr = sum(true_ranges[:period], Decimal(0)) / Decimal(period)
    aligned[period - 1] = atr
    for index in range(period, len(true_ranges)):
        atr = (atr * Decimal(period - 1) + true_ranges[index]) / Decimal(period)
        aligned[index] = atr
    return aligned


def _supertrend(
    candles: tuple[NormalizedCandle, ...],
    *,
    period: int,
    multiplier: Decimal,
) -> tuple[Decimal | None, int | None]:
    atr_values = _atr_aligned(candles, period)
    start = period - 1
    if len(candles) <= start or atr_values[start] is None:
        return None, None

    final_upper: Decimal | None = None
    final_lower: Decimal | None = None
    supertrend: Decimal | None = None
    direction: int | None = None

    for index in range(start, len(candles)):
        atr = atr_values[index]
        if atr is None:
            continue
        candle = candles[index]
        midpoint = (candle.high + candle.low) / Decimal(2)
        basic_upper = midpoint + multiplier * atr
        basic_lower = midpoint - multiplier * atr
        if final_upper is None or final_lower is None or supertrend is None:
            final_upper = basic_upper
            final_lower = basic_lower
            direction = 1 if candle.close >= midpoint else -1
            supertrend = final_lower if direction == 1 else final_upper
            continue

        previous_candle = candles[index - 1]
        previous_upper = final_upper
        previous_lower = final_lower
        previous_supertrend = supertrend
        final_upper = (
            basic_upper
            if basic_upper < previous_upper or previous_candle.close > previous_upper
            else previous_upper
        )
        final_lower = (
            basic_lower
            if basic_lower > previous_lower or previous_candle.close < previous_lower
            else previous_lower
        )
        if previous_supertrend == previous_upper:
            supertrend = final_upper if candle.close <= final_upper else final_lower
        else:
            supertrend = final_lower if candle.close >= final_lower else final_upper
        direction = 1 if supertrend == final_lower else -1

    return supertrend, direction


def _vwap(candles: tuple[NormalizedCandle, ...]) -> Decimal | None:
    total_volume = sum((candle.volume for candle in candles), Decimal(0))
    if total_volume <= 0:
        return None
    total_notional = sum(
        (
            ((candle.high + candle.low + candle.close) / Decimal(3)) * candle.volume
            for candle in candles
        ),
        Decimal(0),
    )
    return total_notional / total_volume


def _obv(candles: tuple[NormalizedCandle, ...]) -> Decimal:
    value = Decimal(0)
    for index in range(1, len(candles)):
        candle = candles[index]
        previous = candles[index - 1]
        if candle.close > previous.close:
            value += candle.volume
        elif candle.close < previous.close:
            value -= candle.volume
    return value


def _vpt(candles: tuple[NormalizedCandle, ...]) -> Decimal:
    value = Decimal(0)
    for index in range(1, len(candles)):
        candle = candles[index]
        previous_close = candles[index - 1].close
        value += candle.volume * (candle.close - previous_close) / previous_close
    return value


def _support_resistance(
    candles: tuple[NormalizedCandle, ...],
    *,
    lookback: int,
) -> tuple[Decimal | None, Decimal | None]:
    if len(candles) < lookback:
        return None, None
    sample = candles[-lookback:]
    return min(candle.low for candle in sample), max(candle.high for candle in sample)
