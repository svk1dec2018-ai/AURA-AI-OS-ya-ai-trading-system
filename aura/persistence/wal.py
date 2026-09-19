from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class WalError(RuntimeError):
    pass


class CorruptWalError(WalError):
    pass


class DuplicateEventError(WalError):
    pass


class WalEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence: int = Field(ge=1)
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    correlation_id: str
    event_type: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = Field(default=1, ge=1)


class JsonlWriteAheadLog:
    """Durable append-only WAL with sequence, event-id and checksum validation.

    Each append is flushed and fsynced by default before returning. A caller may
    therefore apply the corresponding financial state mutation only after this
    method succeeds (write-ahead discipline).
    """

    def __init__(self, path: str | Path, *, fsync: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fsync = fsync
        self._last_sequence = 0
        self._event_ids: set[str] = set()
        if self.path.exists():
            for event in self.read_all():
                self._last_sequence = event.sequence
                self._event_ids.add(event.event_id)

    @staticmethod
    def _canonical_event_json(event: WalEvent) -> str:
        return json.dumps(
            event.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _record_json(cls, event: WalEvent) -> str:
        event_json = cls._canonical_event_json(event)
        checksum = hashlib.sha256(event_json.encode("utf-8")).hexdigest()
        return json.dumps(
            {"event": json.loads(event_json), "checksum": checksum},
            sort_keys=True,
            separators=(",", ":"),
        )

    def append(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str,
        event_id: str | None = None,
    ) -> WalEvent:
        candidate_id = event_id or str(uuid4())
        if candidate_id in self._event_ids:
            raise DuplicateEventError(f"duplicate WAL event id: {candidate_id}")

        event = WalEvent(
            sequence=self._last_sequence + 1,
            event_id=candidate_id,
            correlation_id=correlation_id,
            event_type=event_type,
            payload=payload,
        )
        record = self._record_json(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record)
            handle.write("\n")
            handle.flush()
            if self._fsync:
                os.fsync(handle.fileno())

        self._last_sequence = event.sequence
        self._event_ids.add(event.event_id)
        return event

    def read_all(self) -> list[WalEvent]:
        if not self.path.exists():
            return []

        events: list[WalEvent] = []
        event_ids: set[str] = set()
        expected_sequence = 1
        raw_bytes = self.path.read_bytes()
        if raw_bytes and not raw_bytes.endswith(b"\n"):
            raise CorruptWalError("WAL has an incomplete/truncated final record")

        for line_number, raw_line in enumerate(raw_bytes.splitlines(), start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
                event = WalEvent.model_validate(record["event"])
                stored_checksum = str(record["checksum"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise CorruptWalError(f"invalid WAL record at line {line_number}") from exc

            expected_checksum = hashlib.sha256(
                self._canonical_event_json(event).encode("utf-8")
            ).hexdigest()
            if stored_checksum != expected_checksum:
                raise CorruptWalError(f"checksum mismatch at WAL line {line_number}")
            if event.sequence != expected_sequence:
                raise CorruptWalError(
                    f"WAL sequence gap at line {line_number}: "
                    f"expected {expected_sequence}, got {event.sequence}"
                )
            if event.event_id in event_ids:
                raise CorruptWalError(f"duplicate WAL event id at line {line_number}")

            events.append(event)
            event_ids.add(event.event_id)
            expected_sequence += 1

        return events

    @property
    def last_sequence(self) -> int:
        return self._last_sequence
