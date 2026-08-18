from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aura.agents.deliberation import DeliberationCase, DeliberationMemo
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    AgentRound,
    CEODecisionMemo,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.evolution.brain_online import BrainReplayStore
from aura.evolution.shadow_outcomes import ShadowDecisionOutcomeRecorder, ShadowOutcomePolicy
from aura.runtime.scanner import MarketScanResult, ScanCandidate


def _candle(close_time: datetime, price: str) -> NormalizedCandle:
    return NormalizedCandle(
        symbol="XAUUSD",
        venue="EXNESS_MT5_DEMO",
        timeframe="1m",
        open_time=close_time - timedelta(minutes=1),
        close_time=close_time,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal(100),
        closed=True,
    )


def _evidence(
    *,
    agent_id: str,
    role: AgentRole,
    now: datetime,
    confidence: float,
    thesis: str,
    features: dict | None = None,
) -> AgentEvidence:
    return AgentEvidence(
        agent_id=agent_id,
        role=role,
        intent=SignalIntent.LONG,
        confidence=confidence,
        thesis=thesis,
        sources=(
            EvidenceSource(
                source_id=f"test:{agent_id}",
                source_type=EvidenceSourceType.MARKET_DATA,
                observed_at=now,
                trust_score=1.0,
            ),
        ),
        features=features or {},
        generated_at=now,
    )


def _candidate(now: datetime) -> ScanCandidate:
    evidence = (
        _evidence(
            agent_id="tech",
            role=AgentRole.TECHNICAL,
            now=now,
            confidence=0.8,
            thesis="trend",
        ),
        _evidence(
            agent_id="regime",
            role=AgentRole.REGIME,
            now=now,
            confidence=0.7,
            thesis="trend regime",
            features={"regime": "trend"},
        ),
    )
    round_result = AgentRound(
        correlation_id="decision-1",
        evidence=evidence,
        failures=(),
        started_at=now,
        completed_at=now,
    )
    bull = DeliberationCase(
        intent=SignalIntent.LONG,
        supporting_agents=("tech", "regime"),
        arguments=("trend", "trend regime"),
        weighted_strength=1.5,
    )
    bear = DeliberationCase(
        intent=SignalIntent.SHORT,
        supporting_agents=(),
        arguments=(),
        weighted_strength=0.0,
    )
    deliberation = DeliberationMemo(
        bull_case=bull,
        bear_case=bear,
        neutral_arguments=(),
        counterfactuals=(),
        disagreement_ratio=0.2,
        evidence_count=2,
    )
    memo = CEODecisionMemo(
        correlation_id="decision-1",
        intent=SignalIntent.LONG,
        confidence=0.75,
        supporting_agents=("tech", "regime"),
        opposing_agents=(),
        abstaining_agents=(),
        risk_flags=(),
        rationale="long",
        quorum_met=True,
        generated_at=now,
    )
    return ScanCandidate(
        context=AgentContext(
            correlation_id="decision-1",
            symbol="XAUUSD",
            decision_timeframe="1m",
            candles=(_candle(now, "2000"),),
            created_at=now,
            metadata={
                "execution_quality": {
                    "spread_bps": 2.0,
                    "estimated_slippage_bps": 1.0,
                }
            },
        ),
        round=round_result,
        memo=memo,
        data_quality=None,
        deliberation=deliberation,
    )


def test_shadow_outcome_waits_for_future_horizon_and_persists_sample(tmp_path: Path) -> None:
    now = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    store = BrainReplayStore(tmp_path / "replay.jsonl")
    recorder = ShadowDecisionOutcomeRecorder(
        store,
        policy=ShadowOutcomePolicy(horizon_bars=2, fallback_round_trip_cost_bps=2.0),
    )
    scan = MarketScanResult(candidates=(_candidate(now),))
    assert recorder.register_scan(scan) == 1
    assert recorder.on_closed_candles((_candle(now + timedelta(minutes=1), "2010"),)) == ()
    resolved = recorder.on_closed_candles(
        (_candle(now + timedelta(minutes=2), "2020"),)
    )
    assert len(resolved) == 1
    assert resolved[0].net_return_pct > 0
    assert resolved[0].regime == "trend"
    assert resolved[0].deliberation_disagreement == 0.2
    assert resolved[0].execution_spread_bps == 2.0
    assert len(store.read_all()) == 1
    assert recorder.pending_count == 0
