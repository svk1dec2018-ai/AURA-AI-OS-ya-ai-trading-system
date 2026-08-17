from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.external_specialists import (
    CrossMarketSpecialist,
    HigherTimeframeBiasSpecialist,
    KnowledgeMacroSentimentSpecialist,
    OptionsVolatilitySpecialist,
)
from aura.agents.models import AgentContext
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.knowledge.firewall import KnowledgeFirewall, KnowledgeItem, KnowledgeSourceType


def _bar(
    minute: int,
    *,
    timeframe: str = "5m",
    step_minutes: int = 5,
    price: int = 100,
) -> NormalizedCandle:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    value = Decimal(price)
    return NormalizedCandle(
        symbol="X",
        venue="TEST",
        timeframe=timeframe,
        open_time=start,
        close_time=start + timedelta(minutes=step_minutes),
        open=value,
        high=value + Decimal(2),
        low=value - Decimal(1),
        close=value + Decimal(1),
        volume=Decimal(100),
        closed=True,
    )


def _context(*, metadata: dict | None = None, created_at: datetime | None = None) -> AgentContext:
    candle = _bar(0)
    return AgentContext(
        correlation_id="external-round",
        symbol="X",
        decision_timeframe="5m",
        candles=(candle,),
        metadata=metadata or {},
        created_at=created_at or datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_higher_timeframe_bias_uses_only_closed_point_in_time_bars() -> None:
    htf = [
        _bar(
            index * 60,
            timeframe="1h",
            step_minutes=60,
            price=100 + index,
        ).model_dump(mode="json")
        for index in range(25)
    ]
    context = _context(
        metadata={"htf_candles": htf},
        created_at=datetime(2026, 1, 2, 2, 0, tzinfo=UTC),
    )
    evidence = await HigherTimeframeBiasSpecialist().analyze(context)
    assert evidence.intent == SignalIntent.LONG
    assert evidence.features["htf_timeframe"] == "1h"
    assert evidence.sources[0].observed_at <= evidence.generated_at


@pytest.mark.asyncio
async def test_future_higher_timeframe_bar_forces_abstention() -> None:
    htf = [
        _bar(
            index * 60,
            timeframe="1h",
            step_minutes=60,
            price=100 + index,
        ).model_dump(mode="json")
        for index in range(25)
    ]
    context = _context(
        metadata={"htf_candles": htf},
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    evidence = await HigherTimeframeBiasSpecialist().analyze(context)
    assert evidence.intent == SignalIntent.FLAT
    assert evidence.risk_flags == ("htf_future_data",)


@pytest.mark.asyncio
async def test_options_specialist_is_advisory_and_flags_extreme_volatility() -> None:
    observed_at = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    context = _context(
        metadata={
            "options_snapshot": {
                "source_id": "options-feed:X",
                "underlying_symbol": "X",
                "observed_at": observed_at,
                "implied_volatility": 0.42,
                "iv_percentile": 92.0,
                "put_call_oi_ratio": 2.0,
                "put_call_volume_ratio": 1.2,
                "trust_score": 0.95,
            }
        }
    )
    evidence = await OptionsVolatilitySpecialist().analyze(context)
    assert evidence.intent == SignalIntent.FLAT
    assert "high_implied_volatility" in evidence.risk_flags
    assert "extreme_put_call_open_interest_ratio" in evidence.risk_flags
    assert evidence.sources[0].observed_at == observed_at


@pytest.mark.asyncio
async def test_cross_market_specialist_combines_trusted_related_market_signals() -> None:
    observed_at = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    context = _context(
        metadata={
            "cross_market_observations": [
                {
                    "source_id": "related:a",
                    "related_symbol": "A",
                    "observed_at": observed_at,
                    "intent": "LONG",
                    "confidence": 0.9,
                    "trust_score": 1.0,
                    "rationale": "risk-on confirmation",
                },
                {
                    "source_id": "related:b",
                    "related_symbol": "B",
                    "observed_at": observed_at,
                    "intent": "LONG",
                    "confidence": 0.7,
                    "trust_score": 0.9,
                    "rationale": "positive correlation confirmation",
                },
                {
                    "source_id": "related:c",
                    "related_symbol": "C",
                    "observed_at": observed_at,
                    "intent": "SHORT",
                    "confidence": 0.2,
                    "trust_score": 1.0,
                    "rationale": "small opposing signal",
                },
            ]
        }
    )
    evidence = await CrossMarketSpecialist().analyze(context)
    assert evidence.intent == SignalIntent.LONG
    assert evidence.confidence > 0.5
    assert len(evidence.sources) == 3


def _knowledge_item(
    *,
    item_id: str,
    source_id: str,
    bias: str,
    content: str,
) -> KnowledgeItem:
    observed_at = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    return KnowledgeItem.from_text(
        item_id=item_id,
        source_id=source_id,
        source_type=KnowledgeSourceType.MACRO,
        title=item_id,
        content=content,
        publication_date=observed_at,
        observed_at=observed_at,
        confidence=0.8,
        trust_score=0.9,
        tags=("macro", "X"),
        claims={"market.bias": bias},
    )


@pytest.mark.asyncio
async def test_macro_specialist_uses_trusted_firewall_claims() -> None:
    firewall = KnowledgeFirewall(min_trust_score=0.7)
    firewall.ingest(
        _knowledge_item(
            item_id="macro-one",
            source_id="official-macro",
            bias="LONG",
            content="macro state one",
        )
    )
    context = _context()
    evidence = await KnowledgeMacroSentimentSpecialist(
        firewall,
        required_tags=("macro", "X"),
    ).analyze(context)
    assert evidence.intent == SignalIntent.LONG
    assert evidence.sources[0].trust_score == 0.9


@pytest.mark.asyncio
async def test_macro_contradiction_forces_abstention() -> None:
    firewall = KnowledgeFirewall(min_trust_score=0.7)
    firewall.ingest(
        _knowledge_item(
            item_id="macro-one",
            source_id="source-one",
            bias="LONG",
            content="macro says long",
        )
    )
    firewall.ingest(
        _knowledge_item(
            item_id="macro-two",
            source_id="source-two",
            bias="SHORT",
            content="macro says short",
        )
    )
    evidence = await KnowledgeMacroSentimentSpecialist(firewall).analyze(_context())
    assert evidence.intent == SignalIntent.FLAT
    assert evidence.risk_flags == ("macro_contradiction",)
