from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemoryKind(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    NEGATIVE = "negative"
    INCIDENT = "incident"
    REGIME = "regime"


class MemoryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_id: str = Field(min_length=1)
    kind: MemoryKind
    subject: str = Field(min_length=1)
    content: str = Field(min_length=1)
    observed_at: datetime
    created_at: datetime
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)
    tags: frozenset[str] = frozenset()
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None

    @field_validator("observed_at", "created_at", "expires_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("memory timestamps must be timezone-aware")
        return value


@dataclass(slots=True, frozen=True)
class RetrievedMemory:
    item: MemoryItem
    relevance_score: float


class CognitiveMemoryStore:
    """Layered point-in-time memory inspired by human trading cognition.

    Memory helps agents remember regimes, incidents, mistakes and durable facts,
    but retrieval is strictly as-of-time. Future observations and expired working
    memory cannot leak into historical/backtest decisions.
    """

    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}

    def add(self, item: MemoryItem) -> None:
        existing = self._items.get(item.memory_id)
        if existing is not None and existing != item:
            raise ValueError(f"memory_id collision: {item.memory_id}")
        if item.observed_at > item.created_at:
            raise ValueError("memory cannot be created before its observation exists")
        if item.expires_at is not None and item.expires_at <= item.created_at:
            raise ValueError("memory expiry must be after creation")
        self._items[item.memory_id] = item

    def retrieve(
        self,
        *,
        as_of: datetime,
        subject: str | None = None,
        tags: frozenset[str] = frozenset(),
        kinds: frozenset[MemoryKind] | None = None,
        limit: int = 20,
        half_life: timedelta = timedelta(days=30),
    ) -> tuple[RetrievedMemory, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if half_life <= timedelta(0):
            raise ValueError("half_life must be positive")

        matches: list[RetrievedMemory] = []
        for item in self._items.values():
            if item.observed_at > as_of or item.created_at > as_of:
                continue
            if item.expires_at is not None and item.expires_at <= as_of:
                continue
            if subject is not None and item.subject != subject:
                continue
            if kinds is not None and item.kind not in kinds:
                continue
            if tags and not tags.issubset(item.tags):
                continue

            age_seconds = max((as_of - item.created_at).total_seconds(), 0.0)
            half_life_seconds = half_life.total_seconds()
            decay = math.pow(0.5, age_seconds / half_life_seconds)
            kind_boost = 1.20 if item.kind in {MemoryKind.NEGATIVE, MemoryKind.INCIDENT} else 1.0
            tag_overlap = len(tags & item.tags) / len(tags) if tags else 1.0
            score = item.importance * item.trust_score * decay * kind_boost * tag_overlap
            matches.append(RetrievedMemory(item=item, relevance_score=min(score, 1.0)))

        matches.sort(
            key=lambda retrieved: (
                -retrieved.relevance_score,
                -retrieved.item.observed_at.timestamp(),
                retrieved.item.memory_id,
            )
        )
        return tuple(matches[:limit])

    def snapshot_as_of(self, as_of: datetime) -> tuple[MemoryItem, ...]:
        return tuple(item.item for item in self.retrieve(as_of=as_of, limit=max(len(self._items), 1)))
