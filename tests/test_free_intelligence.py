from datetime import UTC, datetime

from aura.data import free_intelligence
from aura.data.free_intelligence import IntelligenceKind, RssIntelligenceSource


def test_rss_source_dedupes_and_excludes_future_items(monkeypatch) -> None:
    xml = b"""<?xml version='1.0'?>
    <rss><channel>
      <item><title>Policy update</title><link>https://example.test/a</link><pubDate>Tue, 18 Aug 2026 03:00:00 GMT</pubDate></item>
      <item><title>Policy update</title><link>https://example.test/a</link><pubDate>Tue, 18 Aug 2026 03:00:00 GMT</pubDate></item>
      <item><title>Future update</title><link>https://example.test/b</link><pubDate>Tue, 18 Aug 2026 06:00:00 GMT</pubDate></item>
    </channel></rss>"""
    monkeypatch.setattr(free_intelligence, "_bytes_get", lambda _url: xml)
    source = RssIntelligenceSource(
        source="TEST_OFFICIAL",
        url="https://example.test/rss.xml",
        kind=IntelligenceKind.REGULATORY,
        trust_score=1.0,
    )
    events = source.fetch(observed_at=datetime(2026, 8, 18, 4, 0, tzinfo=UTC))
    assert len(events) == 1
    assert events[0].title == "Policy update"
    assert events[0].trust_score == 1.0
    assert events[0].published_at <= events[0].observed_at
