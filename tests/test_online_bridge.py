from datetime import UTC, datetime, timedelta

from aura.domain.models import SignalIntent
from aura.evolution.online_bridge import OpportunityOnlineLearningBridge
from aura.evolution.online_learning import OnlineLearningPolicy, SafeOnlineLearner
from aura.evolution.opportunity_audit import OpportunityAuditRecord, OpportunityOutcome


def _record(outcome: OpportunityOutcome, index: int) -> OpportunityAuditRecord:
    decision = datetime(2026, 8, 18, 4, 0, tzinfo=UTC) + timedelta(minutes=index)
    return OpportunityAuditRecord(
        record_id=f"r-{index}",
        decision_time=decision,
        resolved_time=decision + timedelta(minutes=5),
        symbol="XAUUSD",
        timeframe="1m",
        raw_intent=(
            SignalIntent.LONG
            if outcome != OpportunityOutcome.MISSED_FLAT
            else SignalIntent.FLAT
        ),
        realized_direction=SignalIntent.LONG,
        move_atr_multiple=1.5,
        outcome=outcome,
        memo_confidence=0.8,
    )


def test_opportunity_bridge_updates_online_outcome_state() -> None:
    learner = SafeOnlineLearner(
        OnlineLearningPolicy(
            half_life_events=2,
            minimum_events_for_research=2,
            research_cooldown_events=1,
            max_ewma_wrong_direction_rate=0.2,
        )
    )
    bridge = OpportunityOnlineLearningBridge(learner, market="FX")
    bridge.observe_records(
        [
            _record(OpportunityOutcome.CAPTURED, 0),
            _record(OpportunityOutcome.WRONG_DIRECTION, 1),
        ]
    )
    snapshot = learner.snapshot(market="FX", symbol="XAUUSD")
    assert snapshot.outcomes_seen == 2
    assert snapshot.ewma_capture_rate > 0
    assert snapshot.ewma_wrong_direction_rate > 0
    assert bridge.status()["tracked_states"] == 1
