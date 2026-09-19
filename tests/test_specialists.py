from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.models import AgentContext, AgentRole
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.agents.specialists import (
    RegimeSpecialist,
    SmcIctStructureSpecialist,
    TechnicalSpecialist,
    VolumeVwapSpecialist,
)
from aura.domain.models import NormalizedCandle, SignalIntent


def _trend_with_liquidity_sweep() -> tuple[NormalizedCandle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[NormalizedCandle] = []
    for index in range(29):
        open_price = Decimal(100 + index)
        close_price = open_price + Decimal(1)
        candles.append(
            NormalizedCandle(
                symbol="X",
                venue="TEST",
                timeframe="5m",
                open_time=start + timedelta(minutes=5 * index),
                close_time=start + timedelta(minutes=5 * (index + 1)),
                open=open_price,
                high=close_price + Decimal(1),
                low=open_price - Decimal(1),
                close=close_price,
                volume=Decimal(100),
                closed=True,
            )
        )

    index = 29
    candles.append(
        NormalizedCandle(
            symbol="X",
            venue="TEST",
            timeframe="5m",
            open_time=start + timedelta(minutes=5 * index),
            close_time=start + timedelta(minutes=5 * (index + 1)),
            open=Decimal(129),
            high=Decimal(133),
            low=Decimal(122),
            close=Decimal(132),
            volume=Decimal(300),
            closed=True,
        )
    )
    return tuple(candles)


@pytest.mark.asyncio
async def test_causal_specialists_work_together_in_one_ceo_round() -> None:
    candles = _trend_with_liquidity_sweep()
    context = AgentContext(
        correlation_id="specialists-1",
        symbol="X",
        decision_timeframe="5m",
        candles=candles,
        created_at=candles[-1].close_time,
    )
    agents = [
        TechnicalSpecialist(),
        SmcIctStructureSpecialist(),
        VolumeVwapSpecialist(),
        RegimeSpecialist(),
    ]

    round_result = await MultiAgentOrchestrator(agents, timeout_seconds=1).run_round(context)
    assert round_result.failures == ()
    by_role = {evidence.role: evidence for evidence in round_result.evidence}
    assert by_role[AgentRole.TECHNICAL].intent == SignalIntent.LONG
    assert by_role[AgentRole.SMC_ICT].intent == SignalIntent.LONG
    assert by_role[AgentRole.VOLUME_VWAP].intent == SignalIntent.LONG
    assert by_role[AgentRole.REGIME].intent == SignalIntent.FLAT
    assert by_role[AgentRole.REGIME].features["regime"] == "trend"

    memo = CEOAggregator(min_agents=4, min_distinct_roles=4).synthesize(round_result)
    assert memo.quorum_met
    assert memo.intent == SignalIntent.LONG
    assert set(memo.supporting_agents) == {
        "deterministic:technical:v1",
        "deterministic:smc_ict:v1",
        "deterministic:volume_vwap:v1",
    }
    assert memo.abstaining_agents == ("deterministic:regime:v1",)


@pytest.mark.asyncio
async def test_smc_specialist_detects_causal_sweep_without_future_bars() -> None:
    candles = _trend_with_liquidity_sweep()
    context = AgentContext(
        correlation_id="smc-1",
        symbol="X",
        decision_timeframe="5m",
        candles=candles,
        created_at=candles[-1].close_time,
    )
    evidence = await SmcIctStructureSpecialist().analyze(context)
    assert evidence.intent == SignalIntent.LONG
    assert evidence.features["swept_low"] is True
    assert evidence.features["displacement"] is True
    assert all(source.observed_at <= evidence.generated_at for source in evidence.sources)
