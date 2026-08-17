from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.forecast_specialist import ForecastEnsembleSpecialist
from aura.agents.models import AgentContext
from aura.domain.models import NormalizedCandle, SignalIntent


def _context(metadata):
    start = datetime(2026, 1, 1, tzinfo=UTC)
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
        correlation_id="forecast-round",
        symbol="XAUUSD",
        decision_timeframe="5m",
        candles=(candle,),
        metadata=metadata,
        created_at=candle.close_time,
    )


@pytest.mark.asyncio
async def test_forecast_distribution_fully_above_price_supports_long() -> None:
    generated = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
    evidence = await ForecastEnsembleSpecialist().analyze(
        _context(
            {
                "forecast_ensemble": {
                    "symbol": "XAUUSD",
                    "horizon_steps": 12,
                    "generated_at": generated,
                    "target_timestamp": generated + timedelta(hours=1),
                    "point_forecast": 104.0,
                    "q10": 101.0,
                    "q50": 104.0,
                    "q90": 107.0,
                    "disagreement_score": 0.1,
                    "contributing_models": ["chronos-2", "timesfm-2.5", "moirai-moe"],
                    "total_weight": 2.4,
                }
            }
        )
    )
    assert evidence.intent == SignalIntent.LONG
    assert evidence.confidence > 0
    assert len(evidence.sources) == 3


@pytest.mark.asyncio
async def test_high_model_disagreement_forces_abstention() -> None:
    generated = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
    evidence = await ForecastEnsembleSpecialist(max_disagreement=0.3).analyze(
        _context(
            {
                "forecast_ensemble": {
                    "symbol": "XAUUSD",
                    "horizon_steps": 6,
                    "generated_at": generated,
                    "target_timestamp": generated + timedelta(minutes=30),
                    "point_forecast": 110.0,
                    "q10": 105.0,
                    "q50": 110.0,
                    "q90": 115.0,
                    "disagreement_score": 0.7,
                    "contributing_models": ["a", "b"],
                    "total_weight": 1.5,
                }
            }
        )
    )
    assert evidence.intent == SignalIntent.FLAT
    assert evidence.risk_flags == ("forecast_model_disagreement",)


@pytest.mark.asyncio
async def test_missing_forecast_abstains_without_fabricating_direction() -> None:
    evidence = await ForecastEnsembleSpecialist().analyze(_context({}))
    assert evidence.intent == SignalIntent.FLAT
    assert evidence.risk_flags == ("forecast_missing",)
