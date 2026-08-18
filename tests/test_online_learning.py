from datetime import UTC, datetime, timedelta

import pytest

from aura.evolution.online_learning import (
    OnlineEventKind,
    OnlineLearningEvent,
    OnlineLearningPolicy,
    OutcomeLabel,
    SafeOnlineLearner,
)


def test_online_learner_updates_every_event_but_only_emits_research_trigger() -> None:
    learner = SafeOnlineLearner(
        OnlineLearningPolicy(
            half_life_events=2,
            minimum_events_for_research=3,
            research_cooldown_events=2,
            max_ewma_missed_rate=0.2,
        )
    )
    now = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
    triggers = []
    for index in range(3):
        triggers.append(
            learner.observe(
                OnlineLearningEvent(
                    kind=OnlineEventKind.OUTCOME,
                    market="NSE",
                    symbol="RELIANCE",
                    regime="TREND",
                    observed_at=now + timedelta(seconds=index),
                    outcome=OutcomeLabel.MISSED,
                )
            )
        )
    assert not triggers[0].due
    assert not triggers[1].due
    assert triggers[2].due
    assert any("missed_rate" in reason for reason in triggers[2].reasons)
    snapshot = learner.snapshot(market="NSE", symbol="RELIANCE", regime="TREND")
    assert snapshot.events_seen == 3
    assert snapshot.ewma_missed_rate > 0.2


def test_online_learner_rejects_backward_event_time() -> None:
    learner = SafeOnlineLearner()
    now = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
    learner.observe(
        OnlineLearningEvent(
            kind=OnlineEventKind.MARKET,
            market="FX",
            symbol="XAUUSD",
            observed_at=now,
        )
    )
    with pytest.raises(ValueError, match="moved backward"):
        learner.observe(
            OnlineLearningEvent(
                kind=OnlineEventKind.MARKET,
                market="FX",
                symbol="XAUUSD",
                observed_at=now - timedelta(seconds=1),
            )
        )
