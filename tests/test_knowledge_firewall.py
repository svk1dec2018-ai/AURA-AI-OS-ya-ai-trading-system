from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aura.knowledge.firewall import (
    KnowledgeError,
    KnowledgeFirewall,
    KnowledgeItem,
    KnowledgeSourceType,
)


def _item(
    *,
    item_id: str,
    source_id: str,
    content: str,
    trust: float = 0.9,
    publication_minute: int = 0,
    observed_minute: int = 0,
    claims: dict[str, str] | None = None,
) -> KnowledgeItem:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return KnowledgeItem.from_text(
        item_id=item_id,
        source_id=source_id,
        source_type=KnowledgeSourceType.RESEARCH_PAPER,
        title=item_id,
        content=content,
        publication_date=start + timedelta(minutes=publication_minute),
        observed_at=start + timedelta(minutes=observed_minute),
        confidence=0.9,
        trust_score=trust,
        tags=("gold", "macro"),
        claims=claims,
    )


def test_low_trust_source_is_rejected() -> None:
    firewall = KnowledgeFirewall(min_trust_score=0.7)
    with pytest.raises(KnowledgeError, match="below required"):
        firewall.ingest(
            _item(item_id="low", source_id="source-low", content="rumor", trust=0.2)
        )


def test_identical_content_is_deduplicated_and_source_updates_are_versioned() -> None:
    firewall = KnowledgeFirewall()
    first = firewall.ingest(
        _item(item_id="a", source_id="official-feed", content="policy unchanged")
    )
    duplicate = firewall.ingest(
        _item(item_id="b", source_id="mirror", content="policy unchanged")
    )
    update = firewall.ingest(
        _item(item_id="c", source_id="official-feed", content="policy changed")
    )

    assert duplicate.item_id == first.item_id
    assert first.version == 1
    assert update.version == 2


def test_future_or_not_yet_observed_material_is_invisible_to_decision() -> None:
    firewall = KnowledgeFirewall()
    firewall.ingest(
        _item(item_id="known", source_id="s1", content="known now", publication_minute=0)
    )
    firewall.ingest(
        _item(
            item_id="future",
            source_id="s2",
            content="published later",
            publication_minute=10,
            observed_minute=10,
        )
    )

    bundle = firewall.build_bundle(as_of=datetime(2026, 1, 1, 0, 5, tzinfo=UTC))
    assert [item.item_id for item in bundle.items] == ["known"]


def test_conflicting_claims_are_explicit_and_block_safe_bundle() -> None:
    firewall = KnowledgeFirewall()
    firewall.ingest(
        _item(
            item_id="one",
            source_id="source-one",
            content="claim one",
            claims={"fed.direction": "tightening"},
        )
    )
    firewall.ingest(
        _item(
            item_id="two",
            source_id="source-two",
            content="claim two",
            claims={"fed.direction": "easing"},
        )
    )

    bundle = firewall.build_bundle(as_of=datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    assert not bundle.safe_for_decision
    assert len(bundle.contradictions) == 1
    contradiction = bundle.contradictions[0]
    assert contradiction.claim_key == "fed.direction"
    assert contradiction.values == ("easing", "tightening")
    assert set(contradiction.item_ids) == {"one", "two"}
