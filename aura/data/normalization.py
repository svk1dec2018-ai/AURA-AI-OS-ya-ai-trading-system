from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from aura.domain.models import NormalizedCandle


class CandleNormalizationError(ValueError):
    pass


def normalize_candle(
    *,
    symbol: str,
    venue: str,
    timeframe: str,
    open_time: datetime,
    close_time: datetime,
    open_price: str | float | Decimal,
    high_price: str | float | Decimal,
    low_price: str | float | Decimal,
    close_price: str | float | Decimal,
    volume: str | float | Decimal = "0",
    closed: bool = True,
) -> NormalizedCandle:
    """Convert venue-specific primitive values into AURA's canonical candle model."""

    def dec(value: str | float | Decimal) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise CandleNormalizationError(f"invalid decimal value: {value!r}") from exc

    try:
        return NormalizedCandle(
            symbol=symbol.strip().upper(),
            venue=venue.strip().upper(),
            timeframe=timeframe.strip().lower(),
            open_time=open_time,
            close_time=close_time,
            open=dec(open_price),
            high=dec(high_price),
            low=dec(low_price),
            close=dec(close_price),
            volume=dec(volume),
            closed=closed,
        )
    except ValueError as exc:
        raise CandleNormalizationError(str(exc)) from exc
