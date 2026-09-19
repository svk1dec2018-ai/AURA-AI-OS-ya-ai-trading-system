from __future__ import annotations

from statistics import fmean

from aura.strategy.features import FeatureSnapshot

from .mtf_consensus import Direction, FrameSignal, MultiTimeframeConsensus, Timeframe


def _timeframe(value: str) -> Timeframe:
    normalized = value.strip().upper()
    aliases = {
        "1M": "M1",
        "5M": "M5",
        "15M": "M15",
        "30M": "M30",
        "1H": "H1",
        "4H": "H4",
        "1D": "D1",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return Timeframe(normalized)
    except ValueError as exc:
        raise ValueError(f"unsupported AURA 2 timeframe: {value}") from exc


def feature_snapshot_to_frame(snapshot: FeatureSnapshot) -> FrameSignal:
    """Translate the existing deterministic AURA feature engine into AURA 2 MTF evidence."""

    votes: list[float] = []
    if snapshot.ema_21 is not None and snapshot.ema_50 is not None:
        votes.append(1.0 if snapshot.ema_21 > snapshot.ema_50 else -1.0)
    if snapshot.ema_50 is not None and snapshot.ema_200 is not None:
        votes.append(1.0 if snapshot.ema_50 > snapshot.ema_200 else -1.0)
    if snapshot.supertrend_direction is not None:
        votes.append(1.0 if snapshot.supertrend_direction > 0 else -1.0)
    if snapshot.macd_histogram is not None:
        if snapshot.macd_histogram > 0:
            votes.append(1.0)
        elif snapshot.macd_histogram < 0:
            votes.append(-1.0)
    if snapshot.rsi_14 is not None:
        if snapshot.rsi_14 >= 55:
            votes.append(0.65)
        elif snapshot.rsi_14 <= 45:
            votes.append(-0.65)
    if snapshot.vwap is not None:
        if snapshot.close > snapshot.vwap:
            votes.append(0.55)
        elif snapshot.close < snapshot.vwap:
            votes.append(-0.55)

    raw = fmean(votes) if votes else 0.0
    if raw >= 0.15:
        direction = Direction.BUY
    elif raw <= -0.15:
        direction = Direction.SELL
    else:
        direction = Direction.FLAT

    coverage = min(1.0, len(votes) / 6.0)
    confidence = min(1.0, abs(raw) * 0.70 + coverage * 0.30)

    ema_alignment = 0.0
    if (
        snapshot.ema_21 is not None
        and snapshot.ema_50 is not None
        and snapshot.ema_200 is not None
    ):
        bullish = snapshot.ema_21 > snapshot.ema_50 > snapshot.ema_200
        bearish = snapshot.ema_21 < snapshot.ema_50 < snapshot.ema_200
        ema_alignment = 1.0 if bullish or bearish else 0.35
    supertrend_strength = 0.75 if snapshot.supertrend_direction in {-1, 1} else 0.25
    trend_strength = min(1.0, 0.65 * ema_alignment + 0.35 * supertrend_strength)

    volatility = 0.0
    if snapshot.atr_14 is not None and snapshot.close > 0:
        atr_fraction = float(snapshot.atr_14 / snapshot.close)
        volatility = min(1.0, atr_fraction / 0.02)

    return FrameSignal(
        timeframe=_timeframe(snapshot.timeframe),
        direction=direction,
        confidence=confidence,
        trend_strength=trend_strength,
        volatility=volatility,
    )


def consensus_from_feature_snapshots(
    snapshots: list[FeatureSnapshot] | tuple[FeatureSnapshot, ...],
):
    if not snapshots:
        raise ValueError("AURA 2 requires at least one feature snapshot")
    symbols = {snapshot.symbol for snapshot in snapshots}
    venues = {snapshot.venue for snapshot in snapshots}
    if len(symbols) != 1 or len(venues) != 1:
        raise ValueError("MTF consensus requires one symbol and one venue")
    frames = [feature_snapshot_to_frame(snapshot) for snapshot in snapshots]
    return MultiTimeframeConsensus().evaluate(frames)
