from pathlib import Path

from aura.ops.phase_gates import phase_is_pass
from aura.ops.risk_engine_gate import (
    build_risk_engine_artifacts,
    check_risk_engine_artifacts,
)


def test_phase_three_evidence_vetoes_all_new_risk_violations() -> None:
    stress, violations = build_risk_engine_artifacts()
    assert stress["decision"] == "PASS"
    assert stress["market_data_claimed"] is False
    assert violations["all_new_risk_violations_vetoed"] is True
    assert violations["risk_reduction_preserved_under_kill_switch"] is True
    assert violations["deterministic_replay_matches"] is True
    assert violations["ai_override_authority"] is False
    sized = next(item for item in violations["cases"] if item["case"] == "stop_risk_sizes_quantity")
    assert sized["approved_quantity"] == "300.0"


def test_committed_phase_three_evidence_is_current() -> None:
    root = Path(__file__).resolve().parents[1]
    assert check_risk_engine_artifacts(root) == ()
    assert phase_is_pass(root / "artifacts/governance/phase_gate_status.json", root, 3)
