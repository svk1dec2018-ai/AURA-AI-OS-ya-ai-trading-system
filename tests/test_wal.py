from __future__ import annotations

import json
from pathlib import Path

import pytest

from aura.persistence.wal import CorruptWalError, DuplicateEventError, JsonlWriteAheadLog


def test_wal_round_trip_and_monotonic_sequence(tmp_path: Path) -> None:
    path = tmp_path / "events.wal"
    wal = JsonlWriteAheadLog(path)

    first = wal.append(
        event_type="order.approved",
        payload={"order_id": "o-1", "quantity": "2"},
        correlation_id="decision-1",
        event_id="event-1",
    )
    second = wal.append(
        event_type="fill.applied",
        payload={"fill_id": "f-1", "order_id": "o-1"},
        correlation_id="decision-1",
        event_id="event-2",
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert wal.last_sequence == 2

    reopened = JsonlWriteAheadLog(path)
    events = reopened.read_all()
    assert [event.event_id for event in events] == ["event-1", "event-2"]
    assert reopened.last_sequence == 2


def test_wal_rejects_duplicate_event_id(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "events.wal")
    wal.append(
        event_type="fill.applied",
        payload={"fill_id": "f-1"},
        correlation_id="c-1",
        event_id="same-id",
    )

    with pytest.raises(DuplicateEventError):
        wal.append(
            event_type="fill.applied",
            payload={"fill_id": "f-1"},
            correlation_id="c-1",
            event_id="same-id",
        )


def test_wal_detects_checksum_tampering(tmp_path: Path) -> None:
    path = tmp_path / "events.wal"
    wal = JsonlWriteAheadLog(path, fsync=False)
    wal.append(
        event_type="portfolio.fill",
        payload={"fill_id": "f-1", "price": "100"},
        correlation_id="c-1",
        event_id="event-1",
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    record["event"]["payload"]["price"] = "999"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(CorruptWalError, match="checksum mismatch"):
        JsonlWriteAheadLog(path)


def test_wal_detects_truncated_final_record(tmp_path: Path) -> None:
    path = tmp_path / "events.wal"
    path.write_text('{"event":', encoding="utf-8")

    with pytest.raises(CorruptWalError, match="truncated"):
        JsonlWriteAheadLog(path)
