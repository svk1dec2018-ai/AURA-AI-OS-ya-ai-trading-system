from pathlib import Path

from aura.ops.phase_gates import phase_is_pass
from aura.ops.state_engine_gate import (
    build_state_engine_artifacts,
    check_state_engine_artifacts,
)


def test_phase_two_evidence_exercises_restart_and_mismatch_safety() -> None:
    transitions, reconciliation = build_state_engine_artifacts()
    assert transitions["decision"] == "PASS"
    assert transitions["illegal_terminal_transition_rejected"] is True
    assert reconciliation["restart_recovery_matches"] is True
    assert reconciliation["clean_reconciliation"]["safe_for_new_risk"] is True
    assert reconciliation["mismatch_simulation"]["freezes_new_orders"] is True
    assert reconciliation["live_money_enabled"] is False


def test_committed_phase_two_evidence_is_current() -> None:
    root = Path(__file__).resolve().parents[1]
    assert check_state_engine_artifacts(root) == ()
    assert phase_is_pass(root / "artifacts/governance/phase_gate_status.json", root, 2)
