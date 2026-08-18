from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from aura.data.candle_aggregation import CandleSession, SessionCandleAggregator
from aura.data.dhan_live_full import DhanDeepFullSource
from aura.data.dhan_live_ticker import (
    DhanLiveCredentials,
    build_ticker_subscriptions,
)
from aura.domain.models import NormalizedCandle
from aura.markets.universe import CanonicalInstrument

DhanFullSourceFactory = Callable[[tuple], DhanDeepFullSource]


class DhanDeepMetadataService:
    """Rotate Dhan Full-feed subscriptions over the current radar shortlist.

    Broad discovery stays on cheap Ticker mode. This service spends the expensive
    Full stream only on deep candidates/open positions, builds volume-bearing
    session candles from Full-feed volume deltas, and caches spread/depth/OI
    metadata for the execution and derivatives specialists.
    """

    def __init__(
        self,
        credentials: DhanLiveCredentials,
        instruments: tuple[CanonicalInstrument, ...] | list[CanonicalInstrument],
        *,
        timeframes: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "4h"),
        source_factory: DhanFullSourceFactory | None = None,
    ) -> None:
        self.credentials = credentials
        self._instrument_by_symbol = {
            item.canonical_symbol: item for item in instruments if item.tradable
        }
        self._source_factory = source_factory or (
            lambda subscriptions: DhanDeepFullSource(credentials, subscriptions)
        )
        self._source: DhanDeepFullSource | None = None
        self._worker: asyncio.Task | None = None
        self._active_symbols: tuple[str, ...] = ()
        self._metadata: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._queue: asyncio.Queue[tuple[NormalizedCandle, ...]] = asyncio.Queue()
        self._aggregator = SessionCandleAggregator(
            timeframes=timeframes,
            session=CandleSession(
                timezone="Asia/Kolkata",
                session_start=time(9, 15),
            ),
        )

    @property
    def active_symbols(self) -> tuple[str, ...]:
        return self._active_symbols

    async def update_symbols(self, symbols: tuple[str, ...] | list[str]) -> bool:
        requested = tuple(
            sorted(
                {
                    symbol
                    for symbol in symbols
                    if symbol in self._instrument_by_symbol
                }
            )
        )
        async with self._lock:
            if requested == self._active_symbols:
                return False
            await self._flush_completed(datetime.now(UTC))
            await self._stop_worker_locked()
            self._active_symbols = requested
            self._stop.clear()
            if not requested:
                return True
            instruments = tuple(self._instrument_by_symbol[symbol] for symbol in requested)
            subscriptions = build_ticker_subscriptions(instruments)
            source = self._source_factory(subscriptions)
            self._source = source
            self._worker = asyncio.create_task(self._run_source(source))
            return True

    def metadata_for(
        self,
        symbol: str,
        *,
        decision_time: datetime,
        max_age_seconds: float = 20.0,
    ) -> dict:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        metadata = self._metadata.get(symbol)
        if not metadata:
            return {}
        execution = metadata.get("execution_quality")
        if not isinstance(execution, dict):
            return {}
        raw_observed = execution.get("observed_at")
        if not isinstance(raw_observed, str):
            return {}
        try:
            observed_at = datetime.fromisoformat(raw_observed)
        except ValueError:
            return {}
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return {}
        if observed_at > decision_time:
            return {}
        if decision_time - observed_at > timedelta(seconds=max_age_seconds):
            return {}
        return dict(metadata)

    async def batches(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                yield await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue

    async def stop(self) -> None:
        async with self._lock:
            await self._flush_completed(datetime.now(UTC))
            await self._stop_worker_locked()
            self._active_symbols = ()
            self._stop.set()

    async def _run_source(self, source: DhanDeepFullSource) -> None:
        async for tick in source.ticks():
            metadata = source.metadata_for(tick.symbol)
            if metadata:
                self._metadata[tick.symbol] = metadata
            completed = self._aggregator.on_tick(tick)
            await self._enqueue_grouped(completed)

    async def _flush_completed(self, timestamp: datetime) -> None:
        await self._enqueue_grouped(self._aggregator.flush_until(timestamp))

    async def _enqueue_grouped(
        self,
        candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle],
    ) -> None:
        grouped: dict[datetime, list[NormalizedCandle]] = defaultdict(list)
        for candle in candles:
            grouped[candle.close_time].append(candle)
        for close_time in sorted(grouped):
            batch = tuple(
                sorted(
                    grouped[close_time],
                    key=lambda item: (item.symbol, item.timeframe),
                )
            )
            if batch:
                await self._queue.put(batch)

    async def _stop_worker_locked(self) -> None:
        if self._source is not None:
            self._source.stop()
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self._source = None
        self._worker = None
