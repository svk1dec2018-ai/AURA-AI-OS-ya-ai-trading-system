from datetime import UTC, datetime, timedelta

import pytest

from aura.knowledge.firewall import (
    KnowledgeError,
    KnowledgeFirewall,
    KnowledgeItem,
    KnowledgeSourceType,
)
from aura.knowledge.retrieval import verify_knowledge_use

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(item_id: str, content: str, *, claims=None, observed_at=_NOW) -> KnowledgeItem:
    return KnowledgeItem.from_text(
        item_id=item_id,
        source_id=f"source:{item_id}",
        source_type=KnowledgeSourceType.INTERNAL,
        title=item_id,
        content=content,
        publication_date=_NOW,
        observed_at=observed_at,
        confidence=0.9,
        trust_score=0.9,
        tags=("risk",),
        claims=claims,
    )


def test_retrieval_is_point_in_time_ranked_and_citation_bound() -> None:
    firewall = KnowledgeFirewall()
    firewall.ingest(_item("daily-loss", "Daily loss limit vetoes new portfolio risk."))
    firewall.ingest(
        _item(
            "future-risk",
            "Future portfolio risk evidence.",
            observed_at=_NOW + timedelta(days=2),
        )
    )

    retrieval = firewall.retrieve("daily loss portfolio risk", as_of=_NOW + timedelta(days=1))
    grant = verify_knowledge_use(retrieval, item_ids=("daily-loss",))

    assert [item.item_id for item in retrieval.items] == ["daily-loss"]
    assert retrieval.safe_for_decision
    assert retrieval.untrusted_content is True
    assert retrieval.instruction_authority is False
    assert grant.content_hashes == (retrieval.items[0].content_hash,)
    with pytest.raises(KnowledgeError, match="was not retrieved"):
        verify_knowledge_use(retrieval, item_ids=("invented-citation",))


def test_empty_or_contradictory_retrieval_cannot_be_verified() -> None:
    firewall = KnowledgeFirewall()
    empty = firewall.retrieve("unknown", as_of=_NOW)
    with pytest.raises(KnowledgeError, match="no retrieved evidence"):
        verify_knowledge_use(empty, item_ids=("unknown",))

    firewall.ingest(_item("one", "risk state is open", claims={"risk.state": "open"}))
    firewall.ingest(_item("two", "risk state is closed", claims={"risk.state": "closed"}))
    conflict = firewall.retrieve("risk state", as_of=_NOW)
    assert not conflict.safe_for_decision
    with pytest.raises(KnowledgeError, match="contradictory evidence"):
        verify_knowledge_use(conflict, item_ids=("one",))
