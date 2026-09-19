from __future__ import annotations

import asyncio
import importlib
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from .events import FleetEvent


class EventBus(Protocol):
    async def publish(self, stream: str, event: FleetEvent) -> str: ...

    async def read(
        self,
        stream: str,
        *,
        after_id: str = "0-0",
        block_ms: int = 0,
        count: int = 100,
    ) -> tuple[tuple[str, FleetEvent], ...]: ...

    async def close(self) -> None: ...


@dataclass(slots=True)
class _MemoryRecord:
    record_id: str
    event: FleetEvent


class InMemoryEventBus:
    """Deterministic local/test bus implementing the Redis-stream contract."""

    def __init__(self) -> None:
        self._records: dict[str, list[_MemoryRecord]] = defaultdict(list)
        self._conditions: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)
        self._sequence = 0
        self._closed = False

    async def publish(self, stream: str, event: FleetEvent) -> str:
        if self._closed:
            raise RuntimeError("event bus is closed")
        if not stream.strip():
            raise ValueError("stream is required")
        self._sequence += 1
        record_id = f"{self._sequence}-0"
        self._records[stream].append(_MemoryRecord(record_id=record_id, event=event))
        condition = self._conditions[stream]
        async with condition:
            condition.notify_all()
        return record_id

    async def read(
        self,
        stream: str,
        *,
        after_id: str = "0-0",
        block_ms: int = 0,
        count: int = 100,
    ) -> tuple[tuple[str, FleetEvent], ...]:
        if count <= 0:
            raise ValueError("count must be positive")
        if block_ms < 0:
            raise ValueError("block_ms cannot be negative")

        def available() -> tuple[tuple[str, FleetEvent], ...]:
            after = (self._sequence, 0) if after_id == "$" else _memory_id(after_id)
            rows = [
                (item.record_id, item.event)
                for item in self._records.get(stream, ())
                if _memory_id(item.record_id) > after
            ]
            return tuple(rows[:count])

        rows = available()
        if rows or block_ms == 0:
            return rows

        condition = self._conditions[stream]
        try:
            async with condition:
                await asyncio.wait_for(condition.wait(), timeout=block_ms / 1000)
        except TimeoutError:
            return ()
        return available()

    async def subscribe(
        self,
        stream: str,
        *,
        after_id: str = "0-0",
        block_ms: int = 1000,
    ) -> AsyncIterator[tuple[str, FleetEvent]]:
        cursor = after_id
        while not self._closed:
            rows = await self.read(stream, after_id=cursor, block_ms=block_ms)
            for record_id, event in rows:
                cursor = record_id
                yield record_id, event

    async def close(self) -> None:
        self._closed = True


class RedisStreamsEventBus:
    """Redis Streams transport used by the distributed AURA fleet."""

    def __init__(
        self,
        url: str = "redis://127.0.0.1:6379/0",
        *,
        namespace: str = "aura",
        maxlen: int = 100_000,
        client: Any | None = None,
    ) -> None:
        if not namespace.strip():
            raise ValueError("Redis namespace is required")
        if maxlen <= 0:
            raise ValueError("Redis stream maxlen must be positive")
        self.url = url
        self.namespace = namespace
        self.maxlen = maxlen
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                redis_asyncio = importlib.import_module("redis.asyncio")
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Redis support requires AURA distributed dependencies"
                ) from exc
            self._client = redis_asyncio.from_url(self.url, decode_responses=True)
        return self._client

    def _stream(self, stream: str) -> str:
        normalized = stream.strip().replace(" ", "_")
        if not normalized:
            raise ValueError("stream is required")
        return f"{self.namespace}:{normalized}"

    async def publish(self, stream: str, event: FleetEvent) -> str:
        record_id = await self.client.xadd(
            self._stream(stream),
            {"event": event.model_dump_json()},
            maxlen=self.maxlen,
            approximate=True,
        )
        return str(record_id)

    async def read(
        self,
        stream: str,
        *,
        after_id: str = "0-0",
        block_ms: int = 0,
        count: int = 100,
    ) -> tuple[tuple[str, FleetEvent], ...]:
        if count <= 0:
            raise ValueError("count must be positive")
        if block_ms < 0:
            raise ValueError("block_ms cannot be negative")
        rows = await self.client.xread(
            {self._stream(stream): after_id},
            block=block_ms or None,
            count=count,
        )
        parsed: list[tuple[str, FleetEvent]] = []
        for _stream_name, records in rows:
            for record_id, fields in records:
                raw = fields.get("event")
                if raw:
                    parsed.append((str(record_id), FleetEvent.model_validate_json(raw)))
        return tuple(parsed)

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def close(self) -> None:
        if self._client is None:
            return
        close = getattr(self._client, "aclose", None)
        if callable(close):
            await close()
        else:
            await self._client.close()


def _memory_id(value: str) -> tuple[int, int]:
    try:
        left, right = value.split("-", 1)
        return int(left), int(right)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid stream id: {value}") from exc
