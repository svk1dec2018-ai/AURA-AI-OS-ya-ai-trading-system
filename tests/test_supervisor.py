from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aura.execution.reconciliation import ReconciliationReport
from aura.risk.engine import RiskEngine, RiskLimits
from aura.runtime.supervisor import HealthStatus, OperationalSupervisor


def test_stale_feed_engages_kill_switch_and_clean_feed_does_not_auto_reset() -> None:
    risk = RiskEngine(RiskLimits())
    supervisor = OperationalSupervisor(risk)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    stale = supervisor.assess_feed_freshness(
        component="kraken:BTC/USD:1m",
        last_event_at=now - timedelta(minutes=5),
        now=now,
        max_age=timedelta(minutes=2),
    )
    assert stale.status == HealthStatus.CRITICAL
    assert risk.kill_switch
    assert "kraken:BTC/USD:1m" in risk.kill_switch_reason

    clean = supervisor.assess_feed_freshness(
        component="kraken:BTC/USD:1m",
        last_event_at=now,
        now=now,
        max_age=timedelta(minutes=2),
    )
    assert clean.status == HealthStatus.HEALTHY
    assert risk.kill_switch
    assert not supervisor.snapshot().healthy


def test_future_feed_timestamp_is_critical() -> None:
    risk = RiskEngine(RiskLimits())
    supervisor = OperationalSupervisor(risk)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    health = supervisor.assess_feed_freshness(
        component="feed",
        last_event_at=now + timedelta(seconds=1),
        now=now,
        max_age=timedelta(minutes=1),
    )
    assert health.status == HealthStatus.CRITICAL
    assert risk.kill_switch


def test_clean_reconciliation_is_healthy_without_clearing_manual_freeze() -> None:
    risk = RiskEngine(RiskLimits())
    risk.engage_kill_switch("manual operator freeze")
    supervisor = OperationalSupervisor(risk)
    report = ReconciliationReport(
        issues=(),
        local_open_orders=0,
        broker_open_orders=0,
        compared_positions=0,
    )
    health = supervisor.record_reconciliation(
        report,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert health.status == HealthStatus.HEALTHY
    assert risk.kill_switch
    assert risk.kill_switch_reason == "manual operator freeze"
