from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.agents.deliberation import DeliberationCase, DeliberationMemo
from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.agents.risk_policy import AgentPolicyDecision
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.runtime.opportunity_radar import OpportunityRadar
from aura.runtime.scanner import MarketScanResult, ScanCandidate


def _context(symbol: str, *, rising: bool = True) -> AgentContext:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[NormalizedCandle] = []
    previous = Decimal(100) if rising else Decimal(200)
    step = Decimal("0.5") if rising else Decimal("-0.5")
    for index in range(80):
        close = previous + step
        open_time = start + timedelta(minutes=5 * index)
        candles.append(
            NormalizedCandle(
                symbol=symbol,
                venue="TEST",
                timeframe="5m",
                open_time=open_time,
                close_time=open_time + timedelta(minutes=5),
                open=previous,
                high=max(previous, close) + Decimal(1),
                low=min(previous, close) - Decimal(1),
                close=close,
                volume=Decimal(100 + index),
                closed=True,
            )
        )
        previous = close
    return AgentContext(
        correlation_id=f"radar:{symbol}",
        symbol=symbol,
        decision_timeframe="5m",
        candles=tuple(candles),
        created_at=candles[-1].close_time,
    )


def _candidate(
    symbol: str,
    *,
    confidence: float,
    intent: SignalIntent,
    rising: bool = True,
    allowed: bool = True,
) -> ScanCandidate:
    context = _context(symbol, rising=rising)
    supporting = ("technical", "htf", "volume") if intent != SignalIntent.FLAT else ()
    opposing = ("macro",) if intent != SignalIntent.FLAT else ()
    abstaining = ("regime",)
    memo = CEODecisionMemo(
        correlation_id=context.correlation_id,
        intent=intent,
        confidence=confidence,
        supporting_agents=supporting,
        opposing_agents=opposing,
        abstaining_agents=abstaining,
        risk_flags=(),
        rationale=f"governed {intent.value.lower()} evidence for {symbol}",
        quorum_met=True,
        generated_at=context.created_at,
    )
    round_result = AgentRound(
        correlation_id=context.correlation_id,
        evidence=(),
        failures=(),
        started_at=context.created_at,
        completed_at=context.created_at,
    )
    deliberation = DeliberationMemo(
        bull_case=DeliberationCase(
            intent=SignalIntent.LONG,
            supporting_agents=(),
            arguments=(),
            weighted_strength=0.8 if intent == SignalIntent.LONG else 0.1,
        ),
        bear_case=DeliberationCase(
            intent=SignalIntent.SHORT,
            supporting_agents=(),
            arguments=(),
            weighted_strength=0.8 if intent == SignalIntent.SHORT else 0.1,
        ),
        neutral_arguments=(),
        counterfactuals=(),
        disagreement_ratio=0.05,
        evidence_count=5,
    )
    policy = AgentPolicyDecision(
        allowed=allowed,
        reasons=() if allowed else ("required specialist evidence unavailable",),
    )
    return ScanCandidate(
        context=context,
        round=round_result,
        memo=memo,
        data_quality=None,
        agent_policy=policy,
        deliberation=deliberation,
    )


def test_radar_ranks_actionable_candidates_before_blocked_candidates() -> None:
    scan = MarketScanResult(
        candidates=(
            _candidate("LOW", confidence=0.55, intent=SignalIntent.LONG),
            _candidate("HIGH", confidence=0.90, intent=SignalIntent.LONG),
            _candidate(
                "BLOCKED",
                confidence=0.99,
                intent=SignalIntent.LONG,
                allowed=False,
            ),
        )
    )
    snapshot = OpportunityRadar().rank(scan)

    assert [item.symbol for item in snapshot.items] == ["HIGH", "LOW", "BLOCKED"]
    assert [item.rank for item in snapshot.items] == [1, 2, 3]
    assert len(snapshot.actionable) == 2
    assert snapshot.items[0].score > snapshot.items[1].score
    assert snapshot.items[2].actionable is False
    assert snapshot.items[2].blocked_reasons == (
        "required specialist evidence unavailable",
    )


def test_radar_uses_directional_feature_alignment_without_creating_trade_levels() -> None:
    long_item = OpportunityRadar().rank(
        MarketScanResult(
            candidates=(
                _candidate("UP", confidence=0.8, intent=SignalIntent.LONG, rising=True),
            )
        )
    ).items[0]
    short_item = OpportunityRadar().rank(
        MarketScanResult(
            candidates=(
                _candidate("DOWN", confidence=0.8, intent=SignalIntent.SHORT, rising=False),
            )
        )
    ).items[0]

    assert long_item.technical_alignment >= 0.8
    assert short_item.technical_alignment >= 0.8
    assert long_item.features.ema_8 is not None
    assert short_item.features.ema_8 is not None
    payload = long_item.to_json_dict()
    assert "target" not in payload
    assert "stop_loss" not in payload
    assert payload["features"]["close"] == str(long_item.features.close)


def test_flat_candidate_is_visible_but_not_an_opportunity() -> None:
    snapshot = OpportunityRadar().rank(
        MarketScanResult(
            candidates=(
                _candidate("FLAT", confidence=0.7, intent=SignalIntent.FLAT),
            )
        )
    )
    item = snapshot.items[0]
    assert item.actionable is False
    assert item.technical_alignment == 0.0
    assert "CEO decision is neutral/flat" in item.blocked_reasons
    assert snapshot.actionable == ()


def test_empty_scan_has_explicit_empty_snapshot() -> None:
    payload = OpportunityRadar().rank(MarketScanResult(candidates=())).to_json_dict()
    assert payload == {
        "as_of": None,
        "count": 0,
        "actionable_count": 0,
        "items": [],
    }
