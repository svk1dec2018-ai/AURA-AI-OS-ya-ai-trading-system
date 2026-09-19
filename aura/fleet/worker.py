from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from .bus import EventBus
from .events import FleetEvent, FleetEventKind
from .manifest import FleetService

EventHandler = Callable[[str, FleetEvent], Awaitable[None]]


class FleetWorker:
    """Runnable AURA fleet worker with Redis-stream consumption and heartbeat.

    A generic worker never fabricates business events. It consumes subscribed
    streams, records transport counters and emits only system-health heartbeats.
    Role-specific business handlers are attached explicitly by later services.
    """

    def __init__(
        self,
        service: FleetService,
        bus: EventBus,
        *,
        heartbeat_seconds: float = 5.0,
        handler: EventHandler | None = None,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self.service = service
        self.bus = bus
        self.heartbeat_seconds = heartbeat_seconds
        self.handler = handler
        self._stop = asyncio.Event()
        self._messages_seen = 0
        self._last_event_at: datetime | None = None
        self._last_error: str | None = None

    @property
    def messages_seen(self) -> int:
        return self._messages_seen

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        consumers = [
            asyncio.create_task(self._consume_stream(stream))
            for stream in self.service.subscribes
        ]
        tasks = [heartbeat, *consumers]
        try:
            await self._stop.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._publish_health(state="stopped")

    async def _consume_stream(self, stream: str) -> None:
        cursor = "$"
        while not self._stop.is_set():
            try:
                rows = await self.bus.read(
                    stream,
                    after_id=cursor,
                    block_ms=1000,
                    count=100,
                )
                for record_id, event in rows:
                    cursor = record_id
                    self._messages_seen += 1
                    self._last_event_at = datetime.now(UTC)
                    if self.handler is not None:
                        await self.handler(stream, event)
                self._last_error = None
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(1.0)

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            await self._publish_health(state="running")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.heartbeat_seconds,
                )
            except TimeoutError:
                continue

    async def _publish_health(self, *, state: str) -> None:
        payload: dict[str, Any] = {
            "service_id": self.service.service_id,
            "role": self.service.role.value,
            "state": state,
            "messages_seen": self._messages_seen,
            "last_event_at": (
                self._last_event_at.isoformat()
                if self._last_event_at is not None
                else None
            ),
            "last_error": self._last_error,
            "financial_authority": self.service.financial_authority,
            "business_ready": bool(
                getattr(self.handler, "ready", self.handler is not None)
            ),
            "business_detail": str(
                getattr(
                    self.handler,
                    "detail",
                    "handler attached" if self.handler is not None else "no business handler",
                )
            ),
        }
        event = FleetEvent(
            kind=FleetEventKind.SYSTEM_HEALTH,
            source=self.service.service_id,
            payload=payload,
        )
        try:
            await self.bus.publish("system.health", event)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
