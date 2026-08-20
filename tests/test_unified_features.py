from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.domain.models import NormalizedCandle
from aura.strategy.features import FeatureConfig, UnifiedFeatureEngine


def _candles(count: int, *, step: Decimal = Decimal(1), volume: Decimal = Decimal(100)):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[NormalizedCandle] = []
    previous = Decimal(100)
    for index in range(count):
        close = previous + step
        open_time = start + timedelta(minutes=5 * index)
        candles.append(
            NormalizedCandle(
                symbol="BTC/USD",
                venue="TEST",
                timeframe="5m",
                open_time=open_time,
                close_time=open_time + timedelta(minutes=5),
                open=previous,
                high=max(previous, close) + Decimal(1),
                low=min(previous, close) - Decimal(1),
                close=close,
                volume=volume,
                closed=True,
            )
        )
        previous = close
    return tuple(candles)


def test_feature_engine_produces_full_closed_candle_snapshot() -> None:
    candles = _candles(220)
    snapshot = UnifiedFeatureEngine().compute(candles, decision_time=candles[-1].close_time)

    assert snapshot.symbol == "BTC/USD"
    assert snapshot.bars_used == 220
    assert snapshot.close == candles[-1].close
    assert snapshot.ema_8 is not None
    assert snapshot.ema_21 is not None
    assert snapshot.ema_50 is not None
    assert snapshot.ema_200 is not None
    assert snapshot.ema_8 > snapshot.ema_21 > snapshot.ema_50 > snapshot.ema_200
    assert snapshot.rsi_14 == Decimal(100)
    assert snapshot.macd_line is not None and snapshot.macd_line > 0
    assert snapshot.macd_signal is not None
    assert snapshot.macd_histogram is not None
    assert snapshot.bollinger_lower is not None
    assert snapshot.bollinger_mid is not None
    assert snapshot.bollinger_upper is not None
    assert snapshot.bollinger_lower < snapshot.bollinger_mid < snapshot.bollinger_upper
    assert snapshot.atr_14 is not None and snapshot.atr_14 > 0
    assert snapshot.supertrend is not None
    assert snapshot.supertrend_direction == 1
    assert snapshot.vwap is not None and snapshot.close > snapshot.vwap
    assert snapshot.obv > 0
    assert snapshot.vpt > 0
    assert snapshot.support == min(candle.low for candle in candles[-20:])
    assert snapshot.resistance == max(candle.high for candle in candles[-20:])

    payload = snapshot.to_json_dict()
    assert payload["symbol"] == "BTC/USD"
    assert payload["as_of"] == candles[-1].close_time.isoformat()
    assert payload["ema_200"] == str(snapshot.ema_200)


def test_feature_engine_warmup_is_explicit_not_fabricated() -> None:
    candles = _candles(5)
    snapshot = UnifiedFeatureEngine().compute(candles)

    assert snapshot.ema_8 is None
    assert snapshot.ema_21 is None
    assert snapshot.ema_50 is None
    assert snapshot.ema_200 is None
    assert snapshot.rsi_14 is None
    assert snapshot.macd_line is None
    assert snapshot.macd_signal is None
    assert snapshot.bollinger_mid is None
    assert snapshot.atr_14 is None
    assert snapshot.supertrend is None
    assert snapshot.support is None
    assert snapshot.resistance is None


def test_feature_engine_does_not_invent_vwap_without_volume() -> None:
    snapshot = UnifiedFeatureEngine().compute(_candles(25, volume=Decimal(0)))
    assert snapshot.vwap is None
    assert snapshot.obv == Decimal(0)
    assert snapshot.vpt == Decimal(0)


def test_feature_engine_rejects_open_or_future_candles() -> None:
    candles = list(_candles(20))
    last = candles[-1]
    candles[-1] = last.model_copy(update={"closed": False})
    with pytest.raises(ValueError, match="closed candles only"):
        UnifiedFeatureEngine().compute(candles)

    closed = _candles(20)
    with pytest.raises(ValueError, match="future candle"):
        UnifiedFeatureEngine().compute(
            closed,
            decision_time=closed[-1].open_time,
        )


def test_feature_engine_is_deterministic() -> None:
    candles = _candles(80, step=Decimal("0.25"))
    engine = UnifiedFeatureEngine()
    first = engine.compute(candles)
    second = engine.compute(candles)
    assert first == second


def test_feature_config_rejects_invalid_periods() -> None:
    with pytest.raises(ValueError, match="fast period"):
        FeatureConfig(macd_fast=26, macd_slow=12)
    with pytest.raises(ValueError, match="positive"):
        FeatureConfig(supertrend_multiplier=Decimal(0))
