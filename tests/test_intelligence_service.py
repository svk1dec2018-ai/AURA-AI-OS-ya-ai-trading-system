from datetime import UTC, datetime, timedelta

import pytest

from aura.data.free_intelligence import ExternalIntelligenceEvent, IntelligenceKind
from aura.data.intelligence_service import LiveIntelligenceService


class _Hub:
    def __init__(self, events):
        self.events = events

    async def official_india_events(self):
        return tuple(self.events)

    async def gdelt(self, query: str, *, max_records: int = 50):
        return ()


def _event(event_id: str, published: datetime, observed: datetime):
    return ExternalIntelligenceEvent(
        event_id=event_id,
        source="TEST",
        kind=IntelligenceKind.REGULATORY,
        title=f"event {event_id}",
        published_at=published,
        observed_at=observed,
        trust_score=1.0,
    )


@pytest.mark.asyncio
async def test_intelligence_service_filters_by_original_observation_time() -> None:
    now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    service = LiveIntelligenceService(
        _Hub(
            [
                _event("visible", now - timedelta(minutes=2), now - timedelta(minutes=1)),
                _event("future-observed", now - timedelta(minutes=3), now + timedelta(seconds=1)),
            ]
        ),
        gdelt_queries=(),
    )
    await service.poll_once()
    metadata = service.metadata_for("NIFTY", decision_time=now)
    events = metadata["external_intelligence_events"]
    assert [item["event_id"] for item in events] == ["visible"]
