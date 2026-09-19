from datetime import UTC, datetime, timedelta

import pytest

from aura.knowledge.local_corpus import LocalKnowledgeError, LocalKnowledgeIndex


def test_manifest_loads_authorized_book_and_retrieves_point_in_time(tmp_path) -> None:
    observed = datetime(2026, 8, 19, tzinfo=UTC)
    source = tmp_path / "risk_book.md"
    source.write_text(
        "Position sizing and volatility targeting reduce portfolio risk. " * 100,
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        """{"entry_id":"risk-book","source_id":"user:risk-book","source_type":"book","title":"Risk Book","relative_path":"risk_book.md","publication_date":"2020-01-01T00:00:00Z","license":"user_provided","confidence":0.8,"trust_score":0.9,"tags":["risk","position-sizing"]}\n""",
        encoding="utf-8",
    )

    index = LocalKnowledgeIndex.load(
        tmp_path,
        observed_at=observed,
        chunk_chars=800,
        overlap_chars=100,
    )

    assert len(index.items) > 1
    assert all("license:user_provided" in item.tags for item in index.items)
    assert index.search("portfolio volatility risk", as_of=observed, limit=2)
    assert index.search(
        "portfolio volatility risk",
        as_of=observed - timedelta(seconds=1),
        limit=2,
    ) == ()


def test_manifest_rejects_path_traversal(tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("not allowed", encoding="utf-8")
    (tmp_path / "manifest.jsonl").write_text(
        """{"entry_id":"escape","source_id":"bad","source_type":"video_transcript","title":"Escape","relative_path":"../outside.txt","publication_date":"2020-01-01T00:00:00Z","license":"user_provided"}\n""",
        encoding="utf-8",
    )

    with pytest.raises(LocalKnowledgeError, match="escapes corpus root"):
        LocalKnowledgeIndex.load(tmp_path)


def test_manifest_rejects_unlisted_license(tmp_path) -> None:
    (tmp_path / "book.txt").write_text("content", encoding="utf-8")
    (tmp_path / "manifest.jsonl").write_text(
        """{"entry_id":"bad-license","source_id":"bad","source_type":"book","title":"Bad","relative_path":"book.txt","publication_date":"2020-01-01T00:00:00Z","license":"unknown_web_copy"}\n""",
        encoding="utf-8",
    )

    with pytest.raises(LocalKnowledgeError, match="invalid knowledge manifest"):
        LocalKnowledgeIndex.load(tmp_path)
