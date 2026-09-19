from __future__ import annotations

import hashlib

from aura.data.free_intelligence import (
    ExternalIntelligenceEvent,
    IntelligenceKind,
    MacroObservation,
)
from aura.data.live_plane import DataDomain, LiveDataEvent

_KIND_TO_DOMAIN = {
    IntelligenceKind.NEWS: DataDomain.NEWS,
    IntelligenceKind.REGULATORY: DataDomain.NEWS,
    IntelligenceKind.CENTRAL_BANK: DataDomain.MACRO,
    IntelligenceKind.FILING: DataDomain.FUNDAMENTAL,
    IntelligenceKind.MACRO: DataDomain.MACRO,
}


def intelligence_to_live_events(
    event: ExternalIntelligenceEvent,
) -> tuple[LiveDataEvent, ...]:
    """Convert one sourced event into subject-specific point-in-time hub events."""

    subjects = event.symbols or ("GLOBAL",)
    domain = _KIND_TO_DOMAIN[event.kind]
    payload = {
        "title": event.title,
        "summary": event.summary,
        "url": event.url,
        "topics": list(event.topics),
        "sentiment": event.sentiment,
        "kind": event.kind.value,
        "published_at": event.published_at.isoformat(),
    }
    return tuple(
        LiveDataEvent(
            event_id=_hub_event_id(event.event_id, subject),
            source_id=event.source,
            domain=domain,
            subject=subject,
            observed_at=event.published_at,
            received_at=event.observed_at,
            payload=payload,
            trust_score=event.trust_score,
            point_in_time_safe=True,
        )
        for subject in subjects
    )


def macro_to_live_event(observation: MacroObservation) -> LiveDataEvent:
    return LiveDataEvent(
        event_id=_hub_event_id(
            f"FRED:{observation.series_id}:{observation.observation_date}:{observation.value}",
            observation.series_id,
        ),
        source_id=observation.source,
        domain=DataDomain.MACRO,
        subject=observation.series_id,
        observed_at=observation.observed_at,
        received_at=observation.observed_at,
        payload={
            "series_id": observation.series_id,
            "observation_date": observation.observation_date,
            "value": observation.value,
            "realtime_start": observation.realtime_start,
            "realtime_end": observation.realtime_end,
        },
        trust_score=1.0,
        point_in_time_safe=True,
    )


def _hub_event_id(base: str, subject: str) -> str:
    digest = hashlib.sha256(f"{base}|{subject}".encode()).hexdigest()
    return f"external:{digest}"
