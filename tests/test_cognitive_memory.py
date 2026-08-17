from datetime import UTC, datetime, timedelta

import pytest

from aura.memory.cognitive import CognitiveMemoryStore, MemoryItem, MemoryKind


def test_memory_retrieval_is_point_in_time_safe() -> None:
    store = CognitiveMemoryStore()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    store.add(
        MemoryItem(
            memory_id="known",
            kind=MemoryKind.EPISODIC,
            subject="XAUUSD",
            content="failed breakout during low liquidity",
            observed_at=t0,
            created_at=t0,
            importance=0.8,
            tags=frozenset({"breakout", "liquidity"}),
        )
    )
    store.add(
        MemoryItem(
            memory_id="future",
            kind=MemoryKind.NEGATIVE,
            subject="XAUUSD",
            content="future loss outcome",
            observed_at=t0 + timedelta(days=2),
            created_at=t0 + timedelta(days=2),
            importance=1.0,
            tags=frozenset({"breakout"}),
        )
    )

    retrieved = store.retrieve(
        as_of=t0 + timedelta(days=1),
        subject="XAUUSD",
        tags=frozenset({"breakout"}),
    )
    assert [item.item.memory_id for item in retrieved] == ["known"]


def test_negative_and_incident_memories_get_attention_boost() -> None:
    store = CognitiveMemoryStore()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for memory_id, kind in (("normal", MemoryKind.EPISODIC), ("loss", MemoryKind.NEGATIVE)):
        store.add(
            MemoryItem(
                memory_id=memory_id,
                kind=kind,
                subject="BTCUSDT",
                content=memory_id,
                observed_at=now,
                created_at=now,
                importance=0.7,
            )
        )

    retrieved = store.retrieve(as_of=now, subject="BTCUSDT")
    assert retrieved[0].item.memory_id == "loss"


def test_expired_working_memory_is_not_retrieved() -> None:
    store = CognitiveMemoryStore()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.add(
        MemoryItem(
            memory_id="temporary",
            kind=MemoryKind.WORKING,
            subject="NIFTY",
            content="temporary orderbook imbalance",
            observed_at=now,
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )
    )
    assert store.retrieve(as_of=now + timedelta(minutes=10), subject="NIFTY") == ()


def test_memory_creation_before_observation_is_rejected() -> None:
    store = CognitiveMemoryStore()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="before its observation"):
        store.add(
            MemoryItem(
                memory_id="bad",
                kind=MemoryKind.EPISODIC,
                subject="X",
                content="bad",
                observed_at=now + timedelta(minutes=1),
                created_at=now,
            )
        )
