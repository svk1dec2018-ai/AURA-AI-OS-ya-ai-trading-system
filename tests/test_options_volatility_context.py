from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.external_specialists import OptionsVolatilitySpecialist
from aura.agents.models import AgentContext
from aura.domain.models import NormalizedCandle, SignalIntent


def _context(metadata: dict) -> AgentContext:
    close_time = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="NIFTY-2026-08-27-FUT",
        venue="DHAN_LIVE",
        timeframe="5m",
        open_time=close_time - timedelta(minutes=5),
        close_time=close_time,
        open=Decimal(25600),
        high=Decimal(25660),
        low=Decimal(25590),
        close=Decimal(25640),
        volume=Decimal(1000),
        closed=True,
    )
    return AgentContext(
        correlation_id="options-underlying-aware",
        symbol=candle.symbol,
        decision_timeframe=candle.timeframe,
        candles=(candle,),
        created_at=close_time + timedelta(seconds=1),
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_options_specialist_accepts_underlying_mapping_without_fake_iv_percentile() -> None:
    observed_at = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
    evidence = await OptionsVolatilitySpecialist().analyze(
        _context(
            {
                "underlying_symbol": "NIFTY",
                "options_snapshot": {
                    "source_id": "dhan-option-chain:IDX_I:13:2026-08-27",
                    "underlying_symbol": "NIFTY",
                    "observed_at": observed_at.isoformat(),
                    "implied_volatility": 11.0,
                    "iv_percentile": None,
                    "put_call_oi_ratio": 1.4,
                    "put_call_volume_ratio": 0.9,
                    "trust_score": 1.0,
                },
            }
        )
    )
    assert evidence.intent == SignalIntent.FLAT
    assert "options_symbol_mismatch" not in evidence.risk_flags
    assert "high_implied_volatility" not in evidence.risk_flags
    assert evidence.features["iv_percentile"] is None
    assert evidence.features["put_call_oi_ratio"] == 1.4


@pytest.mark.asyncio
async def test_options_specialist_still_flags_extreme_pcr_when_percentile_unknown() -> None:
    observed_at = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
    evidence = await OptionsVolatilitySpecialist().analyze(
        _context(
            {
                "underlying_symbol": "NIFTY",
                "options_snapshot": {
                    "source_id": "dhan-option-chain:IDX_I:13:2026-08-27",
                    "underlying_symbol": "NIFTY",
                    "observed_at": observed_at.isoformat(),
                    "implied_volatility": 12.0,
                    "iv_percentile": None,
                    "put_call_oi_ratio": 2.1,
                    "put_call_volume_ratio": 1.0,
                    "trust_score": 1.0,
                },
            }
        )
    )
    assert "extreme_put_call_open_interest_ratio" in evidence.risk_flags
