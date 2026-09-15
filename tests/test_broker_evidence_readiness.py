from __future__ import annotations

from pathlib import Path

from aura.ops.broker_evidence_readiness import (
    build_broker_evidence_readiness_report,
    check_broker_evidence_readiness,
)
from aura.ops.phase_gates import phase_is_pass


def test_phase11_readiness_report_refuses_fake_external_success() -> None:
    report = build_broker_evidence_readiness_report()

    assert report["gate_decision"] == "BLOCKED"
    assert report["increment_status"] == "EVIDENCE_VALIDATOR_READY"
    assert all(report["validation_probes"].values())
    assert report["claims"]["external_broker_called"] is False
    assert report["claims"]["external_execution_verified"] is False
    assert report["claims"]["phase11_pass_claimed"] is False
    assert report["authority_boundary"]["validator_can_submit_orders"] is False
    assert report["exact_external_blockers"]


def test_committed_phase11_readiness_is_current_but_gate_is_blocked() -> None:
    root = Path(__file__).resolve().parents[1]
    ledger = root / "artifacts/governance/phase_gate_status.json"

    assert check_broker_evidence_readiness(root) == ()
    assert phase_is_pass(ledger, root, 10) is True
    assert phase_is_pass(ledger, root, 11) is False
