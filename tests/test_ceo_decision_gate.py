from __future__ import annotations

from pathlib import Path

from aura.ops.ceo_decision_gate import (
    build_decision_trace_logs,
    check_ceo_decision_artifacts,
)
from aura.ops.phase_gates import phase_is_pass


def test_phase10_report_proves_reproducible_explainable_decisions() -> None:
    report = build_decision_trace_logs()
    probes = report["reproducibility"]["probes"]

    assert report["decision"] == "PASS"
    assert all(probes.values())
    assert report["primary_decision"]["decision_trace"]["contributions"]
    assert report["primary_decision"]["execution_authority"] is False
    assert report["claims"]["external_market_data_used"] is False
    assert report["claims"]["trading_action_performed"] is False


def test_committed_phase10_evidence_is_current() -> None:
    root = Path(__file__).resolve().parents[1]
    ledger = root / "artifacts/governance/phase_gate_status.json"

    assert check_ceo_decision_artifacts(root) == ()
    assert phase_is_pass(ledger, root, 10) is True
    assert phase_is_pass(ledger, root, 11) is False
