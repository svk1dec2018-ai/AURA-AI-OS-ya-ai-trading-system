from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.knowledge.firewall import KnowledgeItem, KnowledgeSourceType


class LocalKnowledgeError(RuntimeError):
    pass


class KnowledgeLicense(str, Enum):
    PUBLIC_DOMAIN = "public_domain"
    CC_BY_4_0 = "cc_by_4_0"
    CC_BY_SA_4_0 = "cc_by_sa_4_0"
    OFFICIAL_OPEN = "official_open"
    USER_PROVIDED = "user_provided"


class LocalKnowledgeManifestEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_type: KnowledgeSourceType
    title: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    publication_date: datetime
    license: KnowledgeLicense
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    trust_score: float = Field(default=0.7, ge=0.0, le=1.0)
    tags: tuple[str, ...] = ()
    claims: dict[str, str] = Field(default_factory=dict)

    @field_validator("publication_date")
    @classmethod
    def publication_date_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("knowledge publication_date must be timezone-aware")
        return value.astimezone(UTC)


class LocalKnowledgeIndex:
    """License-gated lexical retrieval for local books and transcripts.

    This deliberately does not download copyrighted material. Only text files
    explicitly listed in a local manifest enter the point-in-time firewall.
    """

    manifest_name = "manifest.jsonl"
    allowed_suffixes = frozenset({".md", ".txt"})

    def __init__(self, items: tuple[KnowledgeItem, ...] = ()) -> None:
        self.items = items

    @classmethod
    def load(
        cls,
        root: Path,
        *,
        observed_at: datetime | None = None,
        max_file_bytes: int = 4_000_000,
        chunk_chars: int = 3500,
        overlap_chars: int = 300,
    ) -> LocalKnowledgeIndex:
        observed = observed_at or datetime.now(UTC)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("knowledge observed_at must be timezone-aware")
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if chunk_chars < 500 or not 0 <= overlap_chars < chunk_chars:
            raise ValueError("invalid knowledge chunk settings")
        manifest = root / cls.manifest_name
        if not manifest.exists():
            return cls()
        root_resolved = root.resolve()
        entries: list[LocalKnowledgeManifestEntry] = []
        known_entry_ids: set[str] = set()
        for line_number, line in enumerate(
            manifest.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                entry = LocalKnowledgeManifestEntry.model_validate_json(line)
            except Exception as exc:
                raise LocalKnowledgeError(
                    f"invalid knowledge manifest line {line_number}: {exc}"
                ) from exc
            if entry.entry_id in known_entry_ids:
                raise LocalKnowledgeError(f"duplicate knowledge entry_id: {entry.entry_id}")
            known_entry_ids.add(entry.entry_id)
            entries.append(entry)

        items: list[KnowledgeItem] = []
        for entry in entries:
            path = (root / entry.relative_path).resolve()
            if not path.is_relative_to(root_resolved):
                raise LocalKnowledgeError(
                    f"knowledge path escapes corpus root: {entry.relative_path}"
                )
            if path.suffix.lower() not in cls.allowed_suffixes:
                raise LocalKnowledgeError(
                    f"knowledge file must be .md or .txt: {entry.relative_path}"
                )
            if not path.is_file():
                raise LocalKnowledgeError(f"knowledge file not found: {entry.relative_path}")
            if path.stat().st_size > max_file_bytes:
                raise LocalKnowledgeError(f"knowledge file is too large: {entry.relative_path}")
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                raise LocalKnowledgeError(f"knowledge file is empty: {entry.relative_path}")
            chunks = _chunks(text, chunk_chars=chunk_chars, overlap_chars=overlap_chars)
            for index, chunk in enumerate(chunks, start=1):
                items.append(
                    KnowledgeItem.from_text(
                        item_id=f"{entry.entry_id}:chunk-{index:04d}",
                        source_id=entry.source_id,
                        source_type=entry.source_type,
                        title=f"{entry.title} [chunk {index}/{len(chunks)}]",
                        content=chunk,
                        publication_date=entry.publication_date,
                        observed_at=observed.astimezone(UTC),
                        confidence=entry.confidence,
                        trust_score=entry.trust_score,
                        tags=(*entry.tags, f"license:{entry.license.value}"),
                        claims=entry.claims,
                        version=index,
                    )
                )
        return cls(tuple(items))

    def search(
        self,
        query: str,
        *,
        as_of: datetime,
        limit: int = 6,
    ) -> tuple[KnowledgeItem, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("knowledge search as_of must be timezone-aware")
        if limit <= 0:
            raise ValueError("knowledge search limit must be positive")
        query_tokens = _tokens(query)
        if not query_tokens:
            return ()
        scored: list[tuple[float, KnowledgeItem]] = []
        for item in self.items:
            if item.publication_date > as_of or item.observed_at > as_of:
                continue
            title_tokens = _tokens(item.title)
            content_tokens = _tokens(item.content)
            tag_tokens = _tokens(" ".join(item.tags))
            score = (
                3.0 * len(query_tokens & title_tokens)
                + 1.0 * len(query_tokens & content_tokens)
                + 2.0 * len(query_tokens & tag_tokens)
            )
            if score <= 0:
                continue
            score *= item.trust_score * item.confidence
            scored.append((score, item))
        scored.sort(
            key=lambda pair: (
                -pair[0],
                -pair[1].publication_date.timestamp(),
                pair[1].item_id,
            )
        )
        return tuple(item for _, item in scored[:limit])


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9_-]+", value.lower()))


def _chunks(text: str, *, chunk_chars: int, overlap_chars: int) -> tuple[str, ...]:
    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(normalized) <= chunk_chars:
        return (normalized,)
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        target_end = min(start + chunk_chars, len(normalized))
        end = target_end
        if target_end < len(normalized):
            paragraph = normalized.rfind("\n\n", start + chunk_chars // 2, target_end)
            sentence = normalized.rfind(". ", start + chunk_chars // 2, target_end)
            boundary = max(paragraph, sentence)
            if boundary > start:
                end = boundary + (2 if boundary == paragraph else 1)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap_chars, start + 1)
    return tuple(chunks)
