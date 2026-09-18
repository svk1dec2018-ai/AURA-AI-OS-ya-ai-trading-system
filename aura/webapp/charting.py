from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from math import sqrt
from typing import Any

from aura.data.mt5_demo import MT5DemoClosedCandleSource, OfficialMT5Gateway
from aura.domain.models import NormalizedCandle

SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w")


@dataclass(slots=True, frozen=True)
class IndicatorPoint:
    ema8: float | None
    ema21: float | None
    ema50: float | None
    ema200: float | None
    rsi14: float | None
    atr14: float | None
    bb_mid20: float | None
    bb_upper20: float | None
    bb_lower20: float | None
    vwap: float | None


def mt5_chart_snapshot(
    symbol: str,
    timeframe: str,
    *,
    bars: int = 300,
    gateway: OfficialMT5Gateway | None = None,
) -> dict[str, Any]:
    """Return fully closed DEMO candles plus deterministic technical overlays.

    This function is strictly read-only.  It reuses the current local MT5
    terminal session, requires that session to pass AURA's DEMO guard, skips the
    forming bar through ``MT5DemoClosedCandleSource`` and never calls order APIs.
    """

    normalized_symbol = symbol.strip()
    if not normalized_symbol or len(normalized_symbol) > 120:
        raise ValueError("symbol must be between 1 and 120 characters")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    if not 30 <= bars <= 2000:
        raise ValueError("bars must be between 30 and 2000")

    owned_gateway = gateway is None
    effective_gateway = gateway or OfficialMT5Gateway()
    try:
        account = effective_gateway.connect_current_demo_session()
        resolved_symbol = resolve_chart_symbol(effective_gateway, normalized_symbol)
        effective_gateway.symbol_select(resolved_symbol, True)
        candles = MT5DemoClosedCandleSource(effective_gateway).fetch(
            resolved_symbol,
            timeframe,
            count=bars,
        )
        if len(candles) < 2:
            raise RuntimeError(
                f"insufficient fully closed candles for {resolved_symbol}/{timeframe}"
            )
        indicators = calculate_indicators(candles)
        return {
            "ok": True,
            "mode": "MT5_DEMO_READ_ONLY",
            "requested_symbol": normalized_symbol,
            "symbol": resolved_symbol,
            "timeframe": timeframe,
            "bars": len(candles),
            "account": {
                "login": account.login,
                "server": account.server,
                "currency": account.currency,
            },
            "candles": [
                {
                    "open_time": candle.open_time.isoformat(),
                    "close_time": candle.close_time.isoformat(),
                    "open": _number(candle.open),
                    "high": _number(candle.high),
                    "low": _number(candle.low),
                    "close": _number(candle.close),
                    "volume": _number(candle.volume),
                    **asdict(point),
                }
                for candle, point in zip(candles, indicators, strict=True)
            ],
        }
    finally:
        if owned_gateway:
            effective_gateway.shutdown()



def mt5_live_quote(
    symbol: str,
    *,
    gateway: OfficialMT5Gateway | None = None,
) -> dict[str, Any]:
    """Return a read-only live DEMO quote for dashboard visualization.

    Trading decisions remain closed-candle based. This endpoint exists only so the
    owner chart can display the current broker bid/ask/last price between closes.
    It never calls order_check or order_send.
    """

    normalized_symbol = symbol.strip()
    if not normalized_symbol or len(normalized_symbol) > 120:
        raise ValueError("symbol must be between 1 and 120 characters")

    owned_gateway = gateway is None
    effective_gateway = gateway or OfficialMT5Gateway()
    try:
        account = effective_gateway.connect_current_demo_session()
        resolved_symbol = resolve_chart_symbol(effective_gateway, normalized_symbol)
        effective_gateway.symbol_select(resolved_symbol, True)
        tick = effective_gateway.symbol_info_tick(resolved_symbol)
        if tick is None:
            raise RuntimeError(
                f"MT5 symbol_info_tick failed for {resolved_symbol}: "
                f"{effective_gateway.last_error()}"
            )
        info = effective_gateway.symbol_info(resolved_symbol)
        tick_data = _record(tick)
        info_data = _record(info) if info is not None else {}
        bid = float(tick_data.get("bid") or 0.0)
        ask = float(tick_data.get("ask") or 0.0)
        point = float(info_data.get("point") or 0.0)
        spread_points = (ask - bid) / point if point > 0 and ask >= bid else None
        timestamp_msc = int(tick_data.get("time_msc") or 0)
        timestamp = int(tick_data.get("time") or 0)
        return {
            "ok": True,
            "mode": "MT5_DEMO_READ_ONLY",
            "requested_symbol": normalized_symbol,
            "symbol": resolved_symbol,
            "bid": bid,
            "ask": ask,
            "last": float(tick_data.get("last") or 0.0),
            "volume": float(tick_data.get("volume_real") or tick_data.get("volume") or 0.0),
            "spread_points": spread_points,
            "digits": int(info_data.get("digits") or 0),
            "point": point,
            "time": timestamp,
            "time_msc": timestamp_msc,
            "account": {
                "login_last4": str(account.login)[-4:],
                "server": account.server,
                "currency": account.currency,
            },
            "execution_authority": False,
            "risk_authority": False,
            "order_submission_attempted": False,
        }
    finally:
        if owned_gateway:
            effective_gateway.shutdown()

def resolve_chart_symbol(gateway: OfficialMT5Gateway, requested: str) -> str:
    """Resolve owner-friendly canonical names to tradable broker aliases."""

    direct = gateway.symbol_info(requested)
    if direct is not None and int(_record(direct).get("trade_mode", 0) or 0) != 0:
        return requested
    rows = gateway.symbols_get()
    if rows is None:
        raise ValueError(f"symbol is not exposed by MT5: {requested}")
    requested_key = requested.casefold()
    candidates: list[tuple[int, int, str, str]] = []
    for row in rows:
        data = _record(row)
        name = str(data.get("name") or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key != requested_key and not key.startswith(requested_key):
            continue
        trade_mode = int(data.get("trade_mode", 0) or 0)
        candidates.append((0 if trade_mode != 0 else 1, len(name), key, name))
    for disabled, _length, _key, name in sorted(candidates):
        if disabled:
            continue
        info = gateway.symbol_info(name)
        if info is not None and int(_record(info).get("trade_mode", 0) or 0) != 0:
            return name
    raise ValueError(f"symbol is not exposed by MT5: {requested}")


def _record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    return dict(vars(value))


def calculate_indicators(
    candles: Sequence[NormalizedCandle],
) -> tuple[IndicatorPoint, ...]:
    if not candles:
        return ()
    closes = [float(item.close) for item in candles]
    highs = [float(item.high) for item in candles]
    lows = [float(item.low) for item in candles]
    volumes = [float(item.volume) for item in candles]
    ema8 = _ema(closes, 8)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    rsi14 = _rsi(closes, 14)
    atr14 = _atr(highs, lows, closes, 14)
    bb_mid20, bb_upper20, bb_lower20 = _bollinger(closes, 20, 2.0)
    vwap = _running_vwap(candles, volumes)
    return tuple(
        IndicatorPoint(
            ema8=ema8[index],
            ema21=ema21[index],
            ema50=ema50[index],
            ema200=ema200[index],
            rsi14=rsi14[index],
            atr14=atr14[index],
            bb_mid20=bb_mid20[index],
            bb_upper20=bb_upper20[index],
            bb_lower20=bb_lower20[index],
            vwap=vwap[index],
        )
        for index in range(len(candles))
    )


def _ema(values: Sequence[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    multiplier = 2.0 / (period + 1.0)
    current = seed
    for index in range(period, len(values)):
        current = (values[index] - current) * multiplier + current
        result[index] = current
    return result


def _rsi(values: Sequence[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    result[period] = _rsi_value(avg_gain, avg_loss)
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        result[index] = _rsi_value(avg_gain, avg_loss)
    return result


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    if len(closes) < period:
        return result
    true_ranges: list[float] = []
    for index in range(len(closes)):
        if index == 0:
            tr = highs[index] - lows[index]
        else:
            tr = max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        true_ranges.append(tr)
    current = sum(true_ranges[:period]) / period
    result[period - 1] = current
    for index in range(period, len(closes)):
        current = ((current * (period - 1)) + true_ranges[index]) / period
        result[index] = current
    return result


def _bollinger(
    values: Sequence[float],
    period: int,
    deviations: float,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    middle: list[float | None] = [None] * len(values)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((value - mean) ** 2 for value in window) / period
        std = sqrt(variance)
        middle[index] = mean
        upper[index] = mean + deviations * std
        lower[index] = mean - deviations * std
    return middle, upper, lower


def _running_vwap(
    candles: Sequence[NormalizedCandle],
    volumes: Sequence[float],
) -> list[float | None]:
    result: list[float | None] = []
    cumulative_price_volume = 0.0
    cumulative_volume = 0.0
    for candle, volume in zip(candles, volumes, strict=True):
        typical = (float(candle.high) + float(candle.low) + float(candle.close)) / 3.0
        effective_volume = max(volume, 0.0)
        cumulative_price_volume += typical * effective_volume
        cumulative_volume += effective_volume
        result.append(
            cumulative_price_volume / cumulative_volume
            if cumulative_volume > 0
            else None
        )
    return result


def _number(value: Decimal) -> float:
    return float(value)
