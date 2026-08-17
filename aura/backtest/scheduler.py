from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from aura.domain.models import NormalizedCandle


@dataclass(slots=True, frozen=True)
class MarketCloseBatch:
    close_time: datetime
    candles: tuple[NormalizedCandle, ...]


class MultiSymbolEventScheduler:
    """Merge independent candle series into deterministic point-in-time close batches.

    A batch exposes only candles whose `close_time` equals the current event time.
    Within a batch candles are sorted by canonical symbol/venue/timeframe so
    backtests remain reproducible regardless of input dictionary/list ordering.
    """

    def build(
        self,
        series: dict[str, list[NormalizedCandle] | tuple[NormalizedCandle, ...]],
    ) -> tuple[MarketCloseBatch, ...]:
        if not series:
            raise ValueError("multi-symbol scheduler requires at least one series")

        grouped: dict[datetime, list[NormalizedCandle]] = defaultdict(list)
        seen_keys: set[tuple[str, str, str, datetime]] = set()
        for expected_symbol, candles in series.items():
            if not candles:
                raise ValueError(f"series for {expected_symbol} is empty")
            previous_close: datetime | None = None
            for candle in candles:
                if candle.symbol != expected_symbol:
                    raise ValueError(
                        f"series key {expected_symbol} contains candle for {candle.symbol}"
                    )
                if not candle.closed:
                    raise ValueError("multi-symbol backtest scheduler accepts only closed candles")
                if previous_close is not None and candle.close_time <= previous_close:
                    raise ValueError(
                        f"series for {expected_symbol} is not strictly increasing by close_time"
                    )
                previous_close = candle.close_time
                key = (candle.symbol, candle.venue, candle.timeframe, candle.close_time)
                if key in seen_keys:
                    raise ValueError(f"duplicate candle event: {key}")
                seen_keys.add(key)
                grouped[candle.close_time].append(candle)

        batches: list[MarketCloseBatch] = []
        for close_time in sorted(grouped):
            candles = tuple(
                sorted(
                    grouped[close_time],
                    key=lambda candle: (candle.symbol, candle.venue, candle.timeframe),
                )
            )
            batches.append(MarketCloseBatch(close_time=close_time, candles=candles))
        return tuple(batches)
