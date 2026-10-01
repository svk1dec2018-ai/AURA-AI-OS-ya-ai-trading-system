from __future__ import annotations

import importlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import PrimeEvent


class DuckDBUnavailable(RuntimeError):
    pass


class PrimeTradeMemory:
    """Local analytical event memory backed by optional DuckDB."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            duckdb = importlib.import_module("duckdb")
        except ModuleNotFoundError as exc:
            raise DuckDBUnavailable(
                "Prime analytical memory requires the analytics optional dependency"
            ) from exc
        self._conn = duckdb.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prime_events (
                event_id VARCHAR PRIMARY KEY,
                correlation_id VARCHAR NOT NULL,
                causation_id VARCHAR,
                kind VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                market VARCHAR,
                symbol VARCHAR,
                observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
                received_at TIMESTAMP WITH TIME ZONE NOT NULL,
                payload_json VARCHAR NOT NULL,
                schema_version INTEGER NOT NULL
            )
            """
        )

    def append(self, event: PrimeEvent) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO prime_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                event.event_id,
                event.correlation_id,
                event.causation_id,
                event.kind.value,
                event.source,
                event.market,
                event.symbol,
                event.observed_at,
                event.received_at,
                json.dumps(event.payload, sort_keys=True, separators=(",", ":"), default=str),
                event.schema_version,
            ],
        )

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM prime_events").fetchone()
        return int(row[0]) if row else 0

    def recent(self, *, limit: int = 100) -> tuple[dict[str, Any], ...]:
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        rows = self._conn.execute(
            """
            SELECT event_id, correlation_id, causation_id, kind, source, market, symbol,
                   observed_at, received_at, payload_json, schema_version
            FROM prime_events
            ORDER BY received_at DESC, event_id DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return tuple(
            {
                "event_id": row[0],
                "correlation_id": row[1],
                "causation_id": row[2],
                "kind": row[3],
                "source": row[4],
                "market": row[5],
                "symbol": row[6],
                "observed_at": _iso(row[7]),
                "received_at": _iso(row[8]),
                "payload": json.loads(row[9]),
                "schema_version": row[10],
            }
            for row in rows
        )

    def close(self) -> None:
        self._conn.close()


def _iso(value: datetime | object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)
