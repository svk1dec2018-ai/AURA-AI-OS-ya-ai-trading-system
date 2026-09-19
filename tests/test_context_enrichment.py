from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.agents.context_enrichment import CognitiveContextEnricher
from aura.agents.models import AgentContext
from aura.data.live_plane import DataDomain, LiveDataEvent, LiveDataHub, LiveDataRequirement
from aura.domain.models import NormalizedCandle
from aura.forecast.ensemble import EnsembleForecast
from aura.memory.cognitive import CognitiveMemoryStore, MemoryItem, MemoryKind


def _context() -> AgentContext:
    start = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="XAUUSD",
        venue="TEST",
        timeframe="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(100),
        closed=True,
    )
    return AgentContext(
        correlation_id="cognitive-1",
        symbol="XAUUSD",
        decision_timeframe="5m",
        candles=(candle,),
        created_at=candle.close_time,
    )


def test_enricher_combines_only_point_in_time_memory_live_data_and_forecast() -> None:
    context = _context()
    memory = CognitiveMemoryStore()
    memory.add(
        MemoryItem(
            memory_id="past-loss",
            kind=MemoryKind.NEGATIVE,
            subject="XAUUSD",
            content="low-liquidity breakout failed",
            observed_at=context.created_at - timedelta(days=1),
            created_at=context.created_at - timedelta(days=1),
            importance=0.9,
        )
    )
    memory.add(
        MemoryItem(
            memory_id="future-outcome",
            kind=MemoryKind.EPISODIC,
            subject="XAUUSD",
            content="future information",
            observed_at=context.created_at + timedelta(days=1),
            created_at=context.created_at + timedelta(days=1),
        )
    )
    live = LiveDataHub()
    observed = context.created_at - timedelta(seconds=1)
    live.ingest(
        LiveDataEvent(
            event_id="book-1",
            source_id="feed",
            domain=DataDomain.ORDER_BOOK,
            subject="XAUUSD",
            observed_at=observed,
            received_at=observed,
            payload={"bid": 99.9, "ask": 100.1},
            sequence=1,
        )
    )
    forecast = EnsembleForecast(
        symbol="XAUUSD",
        horizon_steps=12,
        generated_at=context.created_at,
        target_timestamp=context.created_at + timedelta(hours=1),
        point_forecast=104.0,
        q10=101.0,
        q50=104.0,
        q90=107.0,
        disagreement_score=0.1,
        contributing_models=("chronos-2", "timesfm-2.5"),
        total_weight=1.6,
    )

    enriched = CognitiveContextEnricher(memory=memory, live_data=live).enrich(
        context,
        live_requirements=(
            LiveDataRequirement(
                domain=DataDomain.ORDER_BOOK,
                subject="XAUUSD",
                max_age=timedelta(seconds=10),
            ),
        ),
        require_complete_live_data=True,
        forecast=forecast,
    )

    memories = enriched.metadata["cognitive_memory"]
    assert [item["memory_id"] for item in memories] == ["past-loss"]
    assert enriched.metadata["live_data_snapshot"]["complete"] is True
    assert enriched.metadata["live_data_snapshot"]["events"][0]["event_id"] == "book-1"
    assert enriched.metadata["forecast_ensemble"]["q10"] == 101.0
