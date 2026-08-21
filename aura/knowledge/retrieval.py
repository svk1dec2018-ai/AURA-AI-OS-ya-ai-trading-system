from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from aura.knowledge.firewall import KnowledgeContradiction, KnowledgeError, KnowledgeItem


@dataclass(slots=True, frozen=True)
class RetrievedKnowledge:
    """Point-in-time retrieval output; external text is never command authority."""

    query: str
    as_of: datetime
    items: tuple[KnowledgeItem, ...]
    contradictions: tuple[KnowledgeContradiction, ...]
    untrusted_content: bool = True
    instruction_authority: bool = False

    @property
    def safe_for_decision(self) -> bool:
        return bool(self.items) and not self.contradictions


@dataclass(slots=True, frozen=True)
class VerifiedKnowledgeUse:
    query: str
    as_of: datetime
    item_ids: tuple[str, ...]
    content_hashes: tuple[str, ...]
    instruction_authority: bool = False


def rank_knowledge_items(
    items: tuple[KnowledgeItem, ...] | list[KnowledgeItem],
    query: str,
    *,
    limit: int,
) -> tuple[KnowledgeItem, ...]:
    if limit <= 0:
        raise ValueError("knowledge retrieval limit must be positive")
    query_tokens = _tokens(query)
    if not query_tokens:
        return ()
    scored: list[tuple[float, KnowledgeItem]] = []
    for item in items:
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


def verify_knowledge_use(
    retrieval: RetrievedKnowledge,
    *,
    item_ids: tuple[str, ...],
) -> VerifiedKnowledgeUse:
    """Bind downstream use to exact retrieved evidence; reject invented citations."""

    if not retrieval.safe_for_decision:
        reason = "no retrieved evidence" if not retrieval.items else "contradictory evidence"
        raise KnowledgeError(f"knowledge is not safe for decision: {reason}")
    if not item_ids:
        raise KnowledgeError("verified knowledge use requires at least one citation")
    if len(set(item_ids)) != len(item_ids):
        raise KnowledgeError("verified knowledge citations must be unique")
    available = {item.item_id: item for item in retrieval.items}
    missing = sorted(set(item_ids) - set(available))
    if missing:
        raise KnowledgeError(f"citation was not retrieved: {', '.join(missing)}")
    ordered = tuple(sorted(item_ids))
    return VerifiedKnowledgeUse(
        query=retrieval.query,
        as_of=retrieval.as_of,
        item_ids=ordered,
        content_hashes=tuple(available[item_id].content_hash for item_id in ordered),
    )


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9_-]+", value.lower()))
