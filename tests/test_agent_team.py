from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.models import AgentContext, AgentRole
from aura.agents.team import build_default_agent_team
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.knowledge.firewall import KnowledgeFirewall, KnowledgeItem, KnowledgeSourceType


def _decision_candles() -> tuple[NormalizedCandle, ...]:
    start = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
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


def _htf_candles() -> list[dict]:
    start = datetime(2025, 12, 31, 9, 0, tzinfo=UTC)
    candles: list[dict] = []
    for index in range(25):
        price = Decimal(80 + index)
        candle = NormalizedCandle(
            symbol="X",
            venue="TEST",
            timeframe="1h",
            open_time=start + timedelta(hours=index),
            close_time=start + timedelta(hours=index + 1),
            open=price,
            high=price + Decimal(2),
            low=price - Decimal(1),
            close=price + Decimal(1),
            volume=Decimal(500),
            closed=True,
        )
        candles.append(candle.model_dump(mode="json"))
    return candles


def _firewall() -> KnowledgeFirewall:
    firewall = KnowledgeFirewall(min_trust_score=0.7)
    observed_at = datetime(2026, 1, 2, 11, 0, tzinfo=UTC)
    firewall.ingest(
        KnowledgeItem.from_text(
            item_id="macro-approved",
            source_id="official-macro",
            source_type=KnowledgeSourceType.MACRO,
            title="Macro state",
            content="Trusted macro state supporting X",
            publication_date=observed_at,
            observed_at=observed_at,
            confidence=0.8,
            trust_score=0.9,
            tags=("macro", "X"),
            claims={"market.bias": "LONG"},
        )
    )
    return firewall


@pytest.mark.asyncio
async def test_default_team_runs_all_nine_roles_in_one_concurrent_round() -> None:
    candles = _decision_candles()
    observed_at = candles[-1].close_time
    context = AgentContext(
        correlation_id="full-aura-team",
        symbol="X",
        decision_timeframe="5m",
        candles=candles,
        created_at=observed_at,
        metadata={
            "htf_candles": _htf_candles(),
            "options_snapshot": {
                "source_id": "options:X",
                "underlying_symbol": "X",
                "observed_at": observed_at,
                "implied_volatility": 0.25,
                "iv_percentile": 55.0,
                "put_call_oi_ratio": 1.0,
                "put_call_volume_ratio": 1.0,
                "trust_score": 1.0,
            },
            "cross_market_observations": [
                {
                    "source_id": "cross:A",
                    "related_symbol": "A",
                    "observed_at": observed_at,
                    "intent": "LONG",
                    "confidence": 0.8,
                    "trust_score": 1.0,
                    "rationale": "positive related-market confirmation",
                }
            ],
            "execution_quality": {
                "source_id": "book:X",
                "observed_at": observed_at,
                "spread_bps": 2.0,
                "estimated_slippage_bps": 3.0,
                "top_of_book_notional": 100000.0,
                "trust_score": 1.0,
            },
        },
    )

    team = build_default_agent_team(_firewall(), timeout_seconds=1)
    round_result = await team.orchestrator.run_round(context)

    assert round_result.failures == ()
    assert len(round_result.evidence) == 9
    assert {item.role for item in round_result.evidence} == set(AgentRole)

    memo = team.ceo.synthesize(round_result)
    assert memo.quorum_met
    assert memo.intent == SignalIntent.LONG
    assert "deterministic:technical:v1" in memo.supporting_agents
    assert "deterministic:smc_ict:v1" in memo.supporting_agents
    assert "deterministic:volume_vwap:v1" in memo.supporting_agents
    assert "deterministic:htf_bias:v1" in memo.supporting_agents
    assert "knowledge:macro_sentiment:v1" in memo.supporting_agents
    assert "deterministic:cross_market:v1" in memo.supporting_agents
    assert "deterministic:regime:v1" in memo.abstaining_agents
    assert "deterministic:options_volatility:v1" in memo.abstaining_agents
    assert "deterministic:execution_quality:v1" in memo.abstaining_agents
