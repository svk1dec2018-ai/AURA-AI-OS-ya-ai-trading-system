from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeError(RuntimeError):
    pass


class KnowledgeSourceType(str, Enum):
    EXCHANGE = "exchange"
    BROKER = "broker"
    REGULATOR = "regulator"
    RESEARCH_PAPER = "research_paper"
    NEWS = "news"
    MACRO = "macro"
    BOOK = "book"
    INTERNAL = "internal"


class KnowledgeItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_type: KnowledgeSourceType
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    publication_date: datetime
    observed_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    trust_score: float = Field(ge=0.0, le=1.0)
    tags: tuple[str, ...] = ()
    claims: dict[str, str] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)
    content_hash: str = Field(min_length=64, max_length=64)

    @field_validator("publication_date", "observed_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("knowledge timestamps must be timezone-aware")
        return value

    @classmethod
    def from_text(
        cls,
        *,
        item_id: str,
        source_id: str,
        source_type: KnowledgeSourceType,
        title: str,
        content: str,
        publication_date: datetime,
        observed_at: datetime,
        confidence: float,
        trust_score: float,
        tags: tuple[str, ...] = (),
        claims: dict[str, str] | None = None,
        version: int = 1,
    ) -> KnowledgeItem:
        normalized = content.strip()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return cls(
            item_id=item_id,
            source_id=source_id,
            source_type=source_type,
            title=title,
            content=normalized,
            publication_date=publication_date,
            observed_at=observed_at,
            confidence=confidence,
            trust_score=trust_score,
            tags=tuple(sorted(set(tags))),
            claims=dict(claims or {}),
            version=version,
            content_hash=digest,
        )


class KnowledgeContradiction(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_key: str
    values: tuple[str, ...]
    item_ids: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class KnowledgeBundle:
    as_of: datetime
    items: tuple[KnowledgeItem, ...]
    contradictions: tuple[KnowledgeContradiction, ...]

    @property
    def safe_for_decision(self) -> bool:
        return not self.contradictions


class KnowledgeFirewall:
    """Point-in-time, trust-gated knowledge store for AURA research/agent evidence."""

    def __init__(self, *, min_trust_score: float = 0.6) -> None:
        if not 0 <= min_trust_score <= 1:
            raise ValueError("min_trust_score must be between 0 and 1")
        self.min_trust_score = min_trust_score
        self._items_by_id: dict[str, KnowledgeItem] = {}
        self._item_id_by_hash: dict[str, str] = {}
        self._latest_version_by_source: dict[str, int] = {}

    def ingest(self, item: KnowledgeItem) -> KnowledgeItem:
        if item.trust_score < self.min_trust_score:
            raise KnowledgeError(
                f"source trust {item.trust_score:.3f} below required {self.min_trust_score:.3f}"
            )

        duplicate_id = self._item_id_by_hash.get(item.content_hash)
        if duplicate_id is not None:
            return self._items_by_id[duplicate_id]

        existing = self._items_by_id.get(item.item_id)
        if existing is not None:
            if existing.content_hash != item.content_hash:
                raise KnowledgeError("knowledge item_id cannot point to different content")
            return existing

        expected_version = self._latest_version_by_source.get(item.source_id, 0) + 1
        if item.version != expected_version:
            item = item.model_copy(update={"version": expected_version})

        self._items_by_id[item.item_id] = item
        self._item_id_by_hash[item.content_hash] = item.item_id
        self._latest_version_by_source[item.source_id] = item.version
        return item

    def build_bundle(
        self,
        *,
        as_of: datetime,
        required_tags: tuple[str, ...] = (),
    ) -> KnowledgeBundle:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        required = set(required_tags)
        eligible = [
            item
            for item in self._items_by_id.values()
            if item.publication_date <= as_of
            and item.observed_at <= as_of
            and (not required or required.issubset(set(item.tags)))
        ]
        eligible.sort(key=lambda item: (item.publication_date, item.observed_at, item.item_id))
        contradictions = self._find_contradictions(eligible)
        return KnowledgeBundle(
            as_of=as_of,
            items=tuple(eligible),
            contradictions=contradictions,
        )

    @staticmethod
    def _find_contradictions(
        items: list[KnowledgeItem],
    ) -> tuple[KnowledgeContradiction, ...]:
        claims: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for item in items:
            for key, value in item.claims.items():
                claims[key][value].append(item.item_id)

        contradictions: list[KnowledgeContradiction] = []
        for key, values_to_items in claims.items():
            if len(values_to_items) <= 1:
                continue
            values = tuple(sorted(values_to_items))
            item_ids = tuple(
                sorted(
                    item_id
                    for ids in values_to_items.values()
                    for item_id in ids
                )
            )
            contradictions.append(
                KnowledgeContradiction(
                    claim_key=key,
                    values=values,
                    item_ids=item_ids,
                )
            )
        contradictions.sort(key=lambda contradiction: contradiction.claim_key)
        return tuple(contradictions)
