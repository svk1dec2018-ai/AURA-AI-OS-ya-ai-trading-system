from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.evolution.opportunity_audit import (
    MissedOpportunityAuditor,
    OpportunityAuditPolicy,
    OpportunityAuditStore,
    OpportunityOutcome,
)
from aura.runtime.scanner import MarketScanResult, ScanCandidate


def _history(now: datetime) -> tuple[NormalizedCandle, ...]:
    candles: list[NormalizedCandle] = []
    for index in range(20):
        close_time = now - timedelta(minutes=19 - index)
        base = Decimal(2000) + Decimal(index % 3)
        candles.append(
            NormalizedCandle(
                symbol="XAUUSD",
                venue="EXNESS_MT5_DEMO",
                timeframe="1m",
                open_time=close_time - timedelta(minutes=1),
                close_time=close_time,
                open=base,
                high=base + Decimal(2),
                low=base - Decimal(2),
                close=base + Decimal("0.5"),
                volume=Decimal(100),
                closed=True,
            )
        )
    return tuple(candles)


def _future(now: datetime, minute: int, close: str) -> NormalizedCandle:
    price = Decimal(close)
    close_time = now + timedelta(minutes=minute)
    return NormalizedCandle(
        symbol="XAUUSD",
        venue="EXNESS_MT5_DEMO",
        timeframe="1m",
        open_time=close_time - timedelta(minutes=1),
        close_time=close_time,
        open=price,
        high=price + Decimal(1),
        low=price - Decimal(1),
        close=price,
        volume=Decimal(100),
        closed=True,
    )


def _candidate(now: datetime, intent: SignalIntent, correlation_id: str) -> ScanCandidate:
    history = _history(now)
    round_result = AgentRound(
        correlation_id=correlation_id,
        evidence=(),
        failures=(),
        started_at=now,
        completed_at=now,
    )
    memo = CEODecisionMemo(
        correlation_id=correlation_id,
        intent=intent,
        confidence=0.75 if intent != SignalIntent.FLAT else 0.0,
        supporting_agents=(),
        opposing_agents=(),
        abstaining_agents=(),
        risk_flags=(),
        rationale="audit fixture",
        quorum_met=True,
        generated_at=now,
    )
    return ScanCandidate(
        context=AgentContext(
            correlation_id=correlation_id,
            symbol="XAUUSD",
            decision_timeframe="1m",
            candles=history,
            created_at=now,
            metadata={},
        ),
        round=round_result,
        memo=memo,
        data_quality=None,
        agent_policy=None,
        deliberation=None,
    )


def test_live_auditor_records_flat_missed_material_move(tmp_path: Path) -> None:
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    store = OpportunityAuditStore(tmp_path / "opportunities.jsonl")
    auditor = MissedOpportunityAuditor(
        store,
        policy=OpportunityAuditPolicy(horizon_bars=2, min_move_atr_multiple=1.0),
    )
    scan = MarketScanResult(candidates=(_candidate(now, SignalIntent.FLAT, "flat-1"),))
    assert auditor.register_scan(scan) == 1
    assert auditor.on_closed_candles((_future(now, 1, "2005"),)) == ()
    resolved = auditor.on_closed_candles((_future(now, 2, "2012"),))
    assert len(resolved) == 1
    assert resolved[0].outcome == OpportunityOutcome.MISSED_FLAT
    metrics = store.metrics()
    assert metrics.material_opportunities == 1
    assert metrics.missed_flat == 1
    assert metrics.capture_rate == 0.0


def test_live_auditor_records_captured_directional_move(tmp_path: Path) -> None:
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    store = OpportunityAuditStore(tmp_path / "opportunities.jsonl")
    auditor = MissedOpportunityAuditor(
        store,
        policy=OpportunityAuditPolicy(horizon_bars=1, min_move_atr_multiple=1.0),
    )
    scan = MarketScanResult(candidates=(_candidate(now, SignalIntent.LONG, "long-1"),))
    assert auditor.register_scan(scan) == 1
    resolved = auditor.on_closed_candles((_future(now, 1, "2012"),))
    assert len(resolved) == 1
    assert resolved[0].outcome == OpportunityOutcome.CAPTURED
    metrics = store.metrics()
    assert metrics.captured == 1
    assert metrics.capture_rate == 1.0


def test_pending_opportunity_survives_restart_and_counts_each_bar_once(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    path = tmp_path / "opportunities.jsonl"
    policy = OpportunityAuditPolicy(horizon_bars=2, min_move_atr_multiple=1.0)
    auditor = MissedOpportunityAuditor(OpportunityAuditStore(path), policy=policy)
    scan = MarketScanResult(candidates=(_candidate(now, SignalIntent.FLAT, "restart-1"),))

    assert auditor.register_scan(scan) == 1
    first_future_bar = _future(now, 1, "2005")
    assert auditor.on_closed_candles((first_future_bar,)) == ()

    recovered = MissedOpportunityAuditor(OpportunityAuditStore(path), policy=policy)
    assert recovered.recovered_pending_count == 1
    assert recovered.pending_count == 1
    assert recovered.on_closed_candles((first_future_bar,)) == ()
    assert recovered.pending_count == 1

    resolved = recovered.on_closed_candles((_future(now, 2, "2012"),))
    assert len(resolved) == 1
    assert resolved[0].record_id.endswith("restart-1:2026-08-18T09:00:00+00:00")
    assert resolved[0].outcome == OpportunityOutcome.MISSED_FLAT

    final = MissedOpportunityAuditor(OpportunityAuditStore(path), policy=policy)
    assert final.pending_count == 0
    assert len(final.store.read_all()) == 1


def test_pending_checkpoint_rejects_policy_change_with_unresolved_records(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    path = tmp_path / "opportunities.jsonl"
    auditor = MissedOpportunityAuditor(
        OpportunityAuditStore(path),
        policy=OpportunityAuditPolicy(horizon_bars=2),
    )
    auditor.register_scan(
        MarketScanResult(candidates=(_candidate(now, SignalIntent.LONG, "policy-1"),))
    )

    with pytest.raises(RuntimeError, match="policy changed"):
        MissedOpportunityAuditor(
            OpportunityAuditStore(path),
            policy=OpportunityAuditPolicy(horizon_bars=3),
        )
