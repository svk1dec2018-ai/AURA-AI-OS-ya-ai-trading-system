from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from aura.data.free_intelligence import ExternalIntelligenceEvent, FreeIntelligenceHub


class LiveIntelligenceService:
    """Failure-isolated external-information cache with point-in-time reads."""

    def __init__(
        self,
        hub: FreeIntelligenceHub | None = None,
        *,
        include_official_india: bool = True,
        gdelt_queries: tuple[str, ...] = (),
        poll_interval_seconds: float = 60.0,
        max_event_age: timedelta = timedelta(hours=24),
        max_events: int = 2000,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if max_event_age <= timedelta(0):
            raise ValueError("max_event_age must be positive")
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self.hub = hub or FreeIntelligenceHub()
        self.include_official_india = include_official_india
        self.gdelt_queries = tuple(item.strip() for item in gdelt_queries if item.strip())
        self.poll_interval_seconds = poll_interval_seconds
        self.max_event_age = max_event_age
        self.max_events = max_events
        self._events: dict[str, ExternalIntelligenceEvent] = {}
        self._worker: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_errors: dict[str, str] = {}
        self.last_poll_at: datetime | None = None

    async def start(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._stop.clear()
        await self.poll_once()
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None

    async def poll_once(self) -> int:
        calls: list[tuple[str, object]] = []
        if self.include_official_india:
            calls.append(("official_india", self.hub.official_india_events()))
        for query in self.gdelt_queries:
            calls.append((f"gdelt:{query}", self.hub.gdelt(query, max_records=50)))
        if not calls:
            self.last_poll_at = datetime.now(UTC)
            return 0
        results = await asyncio.gather(
            *(call for _, call in calls),
            return_exceptions=True,
        )
        added = 0
        for (source_key, _), result in zip(calls, results, strict=True):
            if isinstance(result, Exception):
                self.last_errors[source_key] = f"{type(result).__name__}: {result}"
                continue
            self.last_errors.pop(source_key, None)
            for event in result:
                if event.event_id not in self._events:
                    added += 1
                self._events[event.event_id] = event
        now = datetime.now(UTC)
        cutoff = now - self.max_event_age
        eligible = [
            item
            for item in self._events.values()
            if item.published_at >= cutoff and item.observed_at >= cutoff
        ]
        eligible.sort(
            key=lambda item: (item.published_at, item.observed_at, item.event_id),
            reverse=True,
        )
        self._events = {item.event_id: item for item in eligible[: self.max_events]}
        self.last_poll_at = now
        return added

    def metadata_for(
        self,
        symbol: str,
        *,
        decision_time: datetime,
        limit: int = 50,
    ) -> dict:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        if limit <= 0:
            raise ValueError("limit must be positive")
        normalized_symbol = symbol.upper()
        visible = [
            item
            for item in self._events.values()
            if item.published_at <= decision_time
            and item.observed_at <= decision_time
            and (
                not item.symbols
                or normalized_symbol in {value.upper() for value in item.symbols}
            )
        ]
        visible.sort(
            key=lambda item: (item.published_at, item.observed_at, item.event_id),
            reverse=True,
        )
        if not visible:
            return {}
        return {
            "external_intelligence_events": [
                item.model_dump(mode="json") for item in visible[:limit]
            ]
        }

    def status(self) -> dict:
        return {
            "events_cached": len(self._events),
            "last_poll_at": self.last_poll_at.isoformat() if self.last_poll_at else None,
            "errors": dict(self.last_errors),
            "gdelt_queries": list(self.gdelt_queries),
            "official_india_enabled": self.include_official_india,
        }

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.poll_interval_seconds,
                )
            except TimeoutError:
                await self.poll_once()
