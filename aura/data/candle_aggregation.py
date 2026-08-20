from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from aura.domain.models import NormalizedCandle, Tick

# Backward-compatible public name for existing data adapters. The canonical
# contract now lives with AURA's other core entities.
CanonicalTradeTick = Tick


@dataclass(slots=True, frozen=True)
class CandleSession:
    timezone: str = "UTC"
    session_start: time = time(0, 0)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass(slots=True)
class _WorkingCandle:
    symbol: str
    venue: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def update(self, tick: CanonicalTradeTick) -> None:
        self.high = max(self.high, tick.price)
        self.low = min(self.low, tick.price)
        self.close = tick.price
        self.volume += tick.quantity

    def closed_candle(self) -> NormalizedCandle:
        return NormalizedCandle(
            symbol=self.symbol,
            venue=self.venue,
            timeframe=self.timeframe,
            open_time=self.open_time,
            close_time=self.close_time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            closed=True,
        )


_FIXED_TIMEFRAMES = {
    "1s": timedelta(seconds=1),
    "5s": timedelta(seconds=5),
    "15s": timedelta(seconds=15),
    "30s": timedelta(seconds=30),
    "1m": timedelta(minutes=1),
    "3m": timedelta(minutes=3),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
}


class SessionCandleAggregator:
    """Causal trade-tick aggregator anchored to each venue's trading session.

    AURA never fabricates missing bars. A candle closes only when a later tick
    proves its bucket ended or `flush_until` reaches its close time. The timestamp
    retained on `NormalizedCandle` is UTC even when buckets are anchored in local
    exchange time (e.g. India 09:15).
    """

    def __init__(
        self,
        *,
        timeframes: tuple[str, ...] = ("1m", "3m", "5m", "15m", "30m", "1h"),
        session: CandleSession | None = None,
    ) -> None:
        if not timeframes:
            raise ValueError("at least one candle timeframe is required")
        unsupported = set(timeframes) - set(_FIXED_TIMEFRAMES)
        if unsupported:
            raise ValueError(f"unsupported fixed timeframes: {sorted(unsupported)}")
        if len(timeframes) != len(set(timeframes)):
            raise ValueError("candle timeframes must be unique")
        self.timeframes = timeframes
        self.session = session or CandleSession()
        self._working: dict[tuple[str, str], _WorkingCandle] = {}
        self._last_tick_time: dict[str, datetime] = {}

    def on_tick(self, tick: CanonicalTradeTick) -> tuple[NormalizedCandle, ...]:
        prior = self._last_tick_time.get(tick.symbol)
        if prior is not None and tick.timestamp < prior:
            raise ValueError(f"out-of-order tick for {tick.symbol}")
        self._last_tick_time[tick.symbol] = tick.timestamp
        completed: list[NormalizedCandle] = []
        for timeframe in self.timeframes:
            open_time, close_time = self._bucket(tick.timestamp, timeframe)
            key = (tick.symbol, timeframe)
            working = self._working.get(key)
            if working is None:
                self._working[key] = _new_working(tick, timeframe, open_time, close_time)
                continue
            if open_time == working.open_time:
                working.update(tick)
                continue
            if open_time < working.open_time:
                raise ValueError(f"tick moved backward across {timeframe} bucket")
            completed.append(working.closed_candle())
            self._working[key] = _new_working(tick, timeframe, open_time, close_time)
        completed.sort(key=lambda item: (item.close_time, item.symbol, item.timeframe))
        return tuple(completed)

    def flush_until(self, timestamp: datetime) -> tuple[NormalizedCandle, ...]:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("flush timestamp must be timezone-aware")
        completed: list[NormalizedCandle] = []
        remove: list[tuple[str, str]] = []
        for key, working in self._working.items():
            if working.close_time <= timestamp.astimezone(UTC):
                completed.append(working.closed_candle())
                remove.append(key)
        for key in remove:
            del self._working[key]
        completed.sort(key=lambda item: (item.close_time, item.symbol, item.timeframe))
        return tuple(completed)

    def _bucket(self, timestamp: datetime, timeframe: str) -> tuple[datetime, datetime]:
        duration = _FIXED_TIMEFRAMES[timeframe]
        local = timestamp.astimezone(self.session.tz)
        anchor = datetime.combine(local.date(), self.session.session_start, tzinfo=self.session.tz)
        if local < anchor:
            anchor -= timedelta(days=1)
        elapsed = local - anchor
        duration_seconds = int(duration.total_seconds())
        bucket_index = int(elapsed.total_seconds()) // duration_seconds
        local_open = anchor + bucket_index * duration
        local_close = local_open + duration
        return local_open.astimezone(UTC), local_close.astimezone(UTC)


def _new_working(
    tick: CanonicalTradeTick,
    timeframe: str,
    open_time: datetime,
    close_time: datetime,
) -> _WorkingCandle:
    return _WorkingCandle(
        symbol=tick.symbol,
        venue=tick.venue,
        timeframe=timeframe,
        open_time=open_time,
        close_time=close_time,
        open=tick.price,
        high=tick.price,
        low=tick.price,
        close=tick.price,
        volume=tick.quantity,
    )
