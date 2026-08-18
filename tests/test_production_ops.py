from __future__ import annotations

from decimal import Decimal

from aura.ops.health import ComponentHealth, HealthReport, HealthStatus
from aura.ops.preflight import DeploymentMode, ProductionPreflight
from aura.ops.release_gate import ProductionEvidence, ProductionReleaseGate
from aura.research.lifecycle import StrategyStage


def test_public_paper_preflight_is_ready(tmp_path) -> None:
    report = ProductionPreflight(
        mode=DeploymentMode.PAPER,
        runtime_dir=tmp_path / "runtime",
        connectors=("public",),
        env={},
    ).run()
    assert report.ready is True
    assert report.blocking_failures == ()


def test_non_live_preflight_rejects_live_acknowledgement(tmp_path) -> None:
    report = ProductionPreflight(
        mode=DeploymentMode.PAPER,
        runtime_dir=tmp_path,
        connectors=("public",),
        env={"AURA_LIVE_TRADING_ENABLED": "I_UNDERSTAND_AND_APPROVE_LIVE_RISK"},
    ).run()
    assert report.ready is False
    assert any(item.check_id == "live-money-disabled" for item in report.blocking_failures)


def test_demo_preflight_fails_closed_when_credentials_missing(tmp_path) -> None:
    report = ProductionPreflight(
        mode=DeploymentMode.DEMO,
        runtime_dir=tmp_path,
        connectors=("mt5_demo",),
        env={},
    ).run()
    assert report.ready is False
    assert any(item.check_id == "connector-mt5_demo" for item in report.blocking_failures)


def test_live_preflight_requires_approved_strategy_and_human_ack(tmp_path) -> None:
    report = ProductionPreflight(
        mode=DeploymentMode.LIVE,
        runtime_dir=tmp_path,
        connectors=("public",),
        strategy_stage=StrategyStage.PAPER_VALIDATED,
        env={},
    ).run()
    assert report.ready is False
    ids = {item.check_id for item in report.blocking_failures}
    assert {"approved-strategy", "human-live-approval", "explicit-live-risk-ack"} <= ids


def test_live_preflight_can_pass_only_with_explicit_human_approval(tmp_path) -> None:
    report = ProductionPreflight(
        mode=DeploymentMode.LIVE,
        runtime_dir=tmp_path,
        connectors=("public",),
        strategy_stage=StrategyStage.APPROVED,
        env={
            "AURA_HUMAN_LIVE_APPROVAL_ID": "approval-2026-001",
            "AURA_LIVE_TRADING_ENABLED": "I_UNDERSTAND_AND_APPROVE_LIVE_RISK",
        },
    ).run()
    assert report.ready is True


def _evidence(**overrides):
    values = {
        "strategy_id": "alpha",
        "strategy_version": "v1",
        "strategy_stage": StrategyStage.APPROVED,
        "forward_live_trades": 1500,
        "forward_live_days": 45,
        "max_drawdown_pct": Decimal("6.5"),
        "profit_factor": Decimal("1.35"),
        "expectancy": Decimal("0.18"),
        "critical_incidents": 0,
        "reconciliation_failures": 0,
        "unresolved_data_integrity_events": 0,
        "source": "LIVE_BROKER",
    }
    values.update(overrides)
    return ProductionEvidence(**values)


def test_release_gate_accepts_strong_forward_broker_evidence() -> None:
    manifest = ProductionReleaseGate().evaluate(_evidence())
    assert manifest.eligible is True
    assert manifest.reasons == ()
    assert len(manifest.manifest_hash) == 64


def test_release_gate_rejects_public_or_historical_evidence_for_live() -> None:
    manifest = ProductionReleaseGate().evaluate(_evidence(source="LIVE_PUBLIC"))
    assert manifest.eligible is False
    assert any("LIVE_BROKER" in reason for reason in manifest.reasons)


def test_release_gate_rejects_weak_or_operationally_unsafe_candidate() -> None:
    manifest = ProductionReleaseGate().evaluate(
        _evidence(
            forward_live_trades=100,
            forward_live_days=3,
            max_drawdown_pct=Decimal("14"),
            profit_factor=Decimal("0.9"),
            expectancy=Decimal("-0.1"),
            critical_incidents=1,
            reconciliation_failures=2,
            unresolved_data_integrity_events=1,
        )
    )
    assert manifest.eligible is False
    assert len(manifest.reasons) >= 7


def test_health_report_blocks_new_risk_on_degraded_or_kill_switch() -> None:
    healthy = ComponentHealth("market-data", HealthStatus.HEALTHY)
    degraded = ComponentHealth("broker", HealthStatus.DEGRADED, "reconnecting")
    report = HealthReport((healthy, degraded))
    assert report.status == HealthStatus.DEGRADED
    assert report.ready_for_new_risk is False

    killed = HealthReport((healthy,), kill_switch_engaged=True)
    assert killed.status == HealthStatus.UNHEALTHY
    assert killed.ready_for_new_risk is False
