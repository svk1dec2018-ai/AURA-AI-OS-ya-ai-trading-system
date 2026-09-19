from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any


DEFAULT_SSE_STREAMS = (
    "system.health",
    "ml.vote",
    "agents.verdict",
    "risk.decision",
    "execution.fill",
)


class RedisFleetSSE:
    """Synchronous Redis Streams reader for the local HTTP SSE gateway."""

    def __init__(
        self,
        url: str,
        *,
        namespace: str = "aura",
        client: Any | None = None,
    ) -> None:
        self.url = url
        self.namespace = namespace
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                redis = __import__("redis")
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Fleet streaming requires AURA distributed dependencies"
                ) from exc
            self._client = redis.from_url(self.url, decode_responses=True)
        return self._client

    def ping(self) -> bool:
        return bool(self.client.ping())

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def iter_sse(
        self,
        streams: tuple[str, ...] = DEFAULT_SSE_STREAMS,
        *,
        duration_seconds: float = 30.0,
        block_ms: int = 5000,
    ) -> Iterator[bytes]:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if block_ms <= 0:
            raise ValueError("block_ms must be positive")
        if not streams:
            raise ValueError("at least one fleet stream is required")

        cursors = {
            self._stream_name(stream): "$"
            for stream in streams
        }
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            rows = self.client.xread(
                cursors,
                block=block_ms,
                count=100,
            )
            if not rows:
                yield b": heartbeat\n\n"
                continue
            for stream_name, records in rows:
                logical_stream = self._logical_name(str(stream_name))
                for record_id, fields in records:
                    cursors[str(stream_name)] = str(record_id)
                    raw = fields.get("event")
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    payload = json.dumps(
                        {
                            "stream": logical_stream,
                            "record_id": str(record_id),
                            "event": event,
                        },
                        separators=(",", ":"),
                    )
                    yield (
                        "id: "
                        + logical_stream
                        + "|"
                        + str(record_id)
                        + "\n"
                        + "data: "
                        + payload
                        + "\n\n"
                    ).encode("utf-8")

    def _stream_name(self, stream: str) -> str:
        normalized = stream.strip().replace(" ", "_")
        if not normalized:
            raise ValueError("stream is required")
        return f"{self.namespace}:{normalized}"

    def _logical_name(self, stream_name: str) -> str:
        prefix = self.namespace + ":"
        return stream_name.removeprefix(prefix)
