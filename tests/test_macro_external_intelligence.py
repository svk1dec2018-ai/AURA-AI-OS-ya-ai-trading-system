from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.external_specialists import KnowledgeMacroSentimentSpecialist
from aura.agents.models import AgentContext
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.knowledge.firewall import KnowledgeFirewall


def _context(events: list[dict]) -> AgentContext:
    close_time = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="XAUUSD",
        venue="EXNESS_MT5_DEMO",
        timeframe="5m",
        open_time=close_time - timedelta(minutes=5),
        close_time=close_time,
        open=Decimal(2500),
        high=Decimal(2510),
        low=Decimal(2490),
        close=Decimal(2505),
        volume=Decimal(100),
        closed=True,
    )
    return AgentContext(
        correlation_id="macro-live-intelligence",
        symbol=candle.symbol,
        decision_timeframe="5m",
        candles=(candle,),
        created_at=close_time + timedelta(seconds=2),
        metadata={"external_intelligence_events": events},
    )


@pytest.mark.asyncio
async def test_macro_specialist_uses_sourced_sentiment_when_firewall_empty() -> None:
    observed = datetime(2026, 8, 18, 5, 0, 1, tzinfo=UTC)
    evidence = await KnowledgeMacroSentimentSpecialist(KnowledgeFirewall()).analyze(
        _context(
            [
                {
                    "event_id": "event-1",
                    "source": "ALPHA_VANTAGE_NEWS_SENTIMENT",
                    "kind": "news",
                    "title": "Gold sentiment improves",
                    "published_at": observed.isoformat(),
                    "observed_at": observed.isoformat(),
                    "summary": "",
                    "symbols": ["XAUUSD"],
                    "topics": [],
                    "sentiment": 0.7,
                    "trust_score": 0.8,
                }
            ]
        )
    )
    assert evidence.intent == SignalIntent.LONG
    assert evidence.confidence > 0
    assert "external_intelligence_sentiment" in evidence.risk_flags


@pytest.mark.asyncio
async def test_macro_specialist_rejects_future_external_event() -> None:
    future = datetime(2026, 8, 18, 5, 0, 5, tzinfo=UTC)
    evidence = await KnowledgeMacroSentimentSpecialist(KnowledgeFirewall()).analyze(
        _context(
            [
                {
                    "event_id": "future-event",
                    "source": "TEST",
                    "kind": "central_bank",
                    "title": "future",
                    "published_at": future.isoformat(),
                    "observed_at": future.isoformat(),
                    "summary": "",
                    "symbols": [],
                    "topics": [],
                    "sentiment": None,
                    "trust_score": 1.0,
                }
            ]
        )
    )
    assert evidence.intent == SignalIntent.FLAT
    assert "macro_future_data" in evidence.risk_flags
