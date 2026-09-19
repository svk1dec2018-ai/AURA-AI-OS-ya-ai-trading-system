from datetime import UTC, datetime, timedelta

import pytest

from aura.data.live_plane import DataDomain, LiveDataEvent, LiveDataHub, LiveDataRequirement


def _event(event_id: str, minute: int, sequence: int = 1, trust: float = 1.0):
    observed = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    return LiveDataEvent(
        event_id=event_id,
        source_id="source",
        domain=DataDomain.ORDER_BOOK,
        subject="BTCUSDT",
        observed_at=observed,
        received_at=observed + timedelta(seconds=1),
        payload={"bid": 100, "ask": 101},
        trust_score=trust,
        sequence=sequence,
    )


def test_snapshot_returns_latest_fresh_trusted_point_in_time_event() -> None:
    hub = LiveDataHub()
    hub.ingest(_event("one", 1, sequence=1))
    hub.ingest(_event("two", 2, sequence=2))

    snapshot = hub.snapshot(
        as_of=datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
        requirements=(
            LiveDataRequirement(
                domain=DataDomain.ORDER_BOOK,
                subject="BTCUSDT",
                max_age=timedelta(minutes=2),
                min_trust_score=0.8,
            ),
        ),
    )
    assert snapshot.complete
    assert snapshot.events[0].event_id == "two"


def test_future_or_stale_event_cannot_satisfy_requirement() -> None:
    hub = LiveDataHub()
    hub.ingest(_event("old", 1, sequence=1))
    snapshot = hub.snapshot(
        as_of=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        requirements=(
            LiveDataRequirement(
                domain=DataDomain.ORDER_BOOK,
                subject="BTCUSDT",
                max_age=timedelta(minutes=1),
            ),
        ),
    )
    assert not snapshot.complete
    assert len(snapshot.missing_requirements) == 1


def test_non_monotonic_stream_sequence_is_rejected() -> None:
    hub = LiveDataHub()
    hub.ingest(_event("one", 1, sequence=10))
    with pytest.raises(ValueError, match="non-monotonic"):
        hub.ingest(_event("two", 2, sequence=9))


def test_event_received_before_observation_is_rejected() -> None:
    observed = datetime(2026, 1, 1, tzinfo=UTC)
    hub = LiveDataHub()
    with pytest.raises(ValueError, match="received before"):
        hub.ingest(
            LiveDataEvent(
                event_id="bad",
                source_id="source",
                domain=DataDomain.NEWS,
                subject="X",
                observed_at=observed,
                received_at=observed - timedelta(seconds=1),
                payload={"headline": "bad timestamp"},
            )
        )
