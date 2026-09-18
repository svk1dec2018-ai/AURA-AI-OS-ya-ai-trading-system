from datetime import UTC, datetime
from decimal import Decimal

from aura.aura2.feature_bridge import (
    consensus_from_feature_snapshots,
    feature_snapshot_to_frame,
)
from aura.aura2.mtf_consensus import Direction, Timeframe
from aura.strategy.features import FeatureSnapshot


def _snapshot(timeframe: str, bullish: bool) -> FeatureSnapshot:
    close = Decimal("2000")
    if bullish:
        ema21, ema50, ema200 = Decimal("1998"), Decimal("1990"), Decimal("1970")
        macd = Decimal("2.0")
        rsi = Decimal("61")
        vwap = Decimal("1994")
        supertrend_direction = 1
    else:
        ema21, ema50, ema200 = Decimal("2002"), Decimal("2010"), Decimal("2030")
        macd = Decimal("-2.0")
        rsi = Decimal("39")
        vwap = Decimal("2006")
        supertrend_direction = -1
    return FeatureSnapshot(
        symbol="XAUUSD",
        venue="MT5",
        timeframe=timeframe,
        as_of=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
        bars_used=250,
        close=close,
        ema_8=None,
        ema_21=ema21,
        ema_50=ema50,
        ema_200=ema200,
        rsi_14=rsi,
        macd_line=None,
        macd_signal=None,
        macd_histogram=macd,
        bollinger_mid=None,
        bollinger_upper=None,
        bollinger_lower=None,
        atr_14=Decimal("8"),
        supertrend=Decimal("1988") if bullish else Decimal("2012"),
        supertrend_direction=supertrend_direction,
        vwap=vwap,
        obv=Decimal("0"),
        vpt=Decimal("0"),
        support=None,
        resistance=None,
    )


def test_existing_aura_features_translate_to_aura2_signal() -> None:
    signal = feature_snapshot_to_frame(_snapshot("M5", True))
    assert signal.timeframe is Timeframe.M5
    assert signal.direction is Direction.BUY
    assert signal.confidence > 0.70


def test_existing_feature_engine_can_drive_full_mtf_consensus() -> None:
    snapshots = [
        _snapshot("M1", True),
        _snapshot("M5", True),
        _snapshot("M15", True),
        _snapshot("M30", True),
        _snapshot("H1", True),
        _snapshot("H4", True),
        _snapshot("D1", True),
    ]
    result = consensus_from_feature_snapshots(snapshots)
    assert result.direction is Direction.BUY
    assert result.execution_alignment == 1.0
    assert result.higher_timeframe_alignment == 1.0
    assert result.tradeable()
