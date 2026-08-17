from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DataDomain(str, Enum):
    MARKET_TICK = "market_tick"
    ORDER_BOOK = "order_book"
    CANDLE = "candle"
    OPTIONS = "options"
    MACRO = "macro"
    NEWS = "news"
    FUNDAMENTAL = "fundamental"
    CROSS_ASSET = "cross_asset"
    EXECUTION = "execution"


class LiveDataEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    domain: DataDomain
    subject: str = Field(min_length=1)
    observed_at: datetime
    received_at: datetime
    payload: dict[str, Any]
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)
    sequence: int | None = Field(default=None, ge=0)
    point_in_time_safe: bool = True

    @field_validator("observed_at", "received_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("live-data timestamps must be timezone-aware")
        return value


@dataclass(slots=True, frozen=True)
class LiveDataRequirement:
    domain: DataDomain
    subject: str
    max_age: timedelta
    min_trust_score: float = 0.0

    def __post_init__(self) -> None:
        if self.max_age < timedelta(0):
            raise ValueError("max_age cannot be negative")
        if not 0 <= self.min_trust_score <= 1:
            raise ValueError("min_trust_score must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class LiveDataSnapshot:
    as_of: datetime
    events: tuple[LiveDataEvent, ...]
    missing_requirements: tuple[LiveDataRequirement, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_requirements


class LiveDataHub:
    """Provider-neutral event hub for AURA's live market/macro/news data plane.

    Adapters may ingest Dhan, Binance, Kraken, FRED/ALFRED, SEC and other sources.
    Historical/backtest decisions can request an as-of snapshot from the same
    event vocabulary, preserving point-in-time semantics across modes.
    """

    def __init__(self) -> None:
        self._events_by_id: dict[str, LiveDataEvent] = {}
        self._latest_sequence: dict[tuple[str, DataDomain, str], int] = {}

    def ingest(self, event: LiveDataEvent) -> None:
        if not event.point_in_time_safe:
            raise ValueError("non-point-in-time-safe live data is forbidden")
        if event.observed_at > event.received_at:
            raise ValueError("live data cannot be received before it was observed")
        existing = self._events_by_id.get(event.event_id)
        if existing is not None:
            if existing != event:
                raise ValueError(f"event_id collision: {event.event_id}")
            return

        if event.sequence is not None:
            key = (event.source_id, event.domain, event.subject)
            previous = self._latest_sequence.get(key)
            if previous is not None and event.sequence <= previous:
                raise ValueError(
                    f"non-monotonic source sequence for {event.source_id}/{event.subject}: "
                    f"{event.sequence} <= {previous}"
                )
            self._latest_sequence[key] = event.sequence
        self._events_by_id[event.event_id] = event

    def snapshot(
        self,
        *,
        as_of: datetime,
        requirements: tuple[LiveDataRequirement, ...],
    ) -> LiveDataSnapshot:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")

        selected: list[LiveDataEvent] = []
        missing: list[LiveDataRequirement] = []
        for requirement in requirements:
            candidates = [
                event
                for event in self._events_by_id.values()
                if event.domain == requirement.domain
                and event.subject == requirement.subject
                and event.observed_at <= as_of
                and event.received_at <= as_of
                and event.trust_score >= requirement.min_trust_score
                and as_of - event.observed_at <= requirement.max_age
            ]
            if not candidates:
                missing.append(requirement)
                continue
            candidates.sort(
                key=lambda event: (
                    event.observed_at,
                    event.received_at,
                    event.sequence if event.sequence is not None else -1,
                    event.event_id,
                ),
                reverse=True,
            )
            selected.append(candidates[0])

        selected.sort(key=lambda event: (event.domain.value, event.subject, event.source_id))
        return LiveDataSnapshot(
            as_of=as_of,
            events=tuple(selected),
            missing_requirements=tuple(missing),
        )
