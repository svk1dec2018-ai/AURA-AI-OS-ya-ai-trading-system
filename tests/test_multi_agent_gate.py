from pathlib import Path

from aura.ops.multi_agent_gate import (
    build_agent_consistency_report,
    check_multi_agent_artifacts,
)
from aura.ops.phase_gates import phase_is_pass


def test_phase_nine_report_is_deterministic_and_advisory_only() -> None:
    first = build_agent_consistency_report()
    second = build_agent_consistency_report()

    assert first == second
    assert first["decision"] == "PASS"
    assert first["specialists"]["count"] == 10
    assert all(first["consistency"]["probes"].values())
    assert first["authority_boundary"]["specialists_can_submit_orders"] is False
    assert first["claims"]["external_ai_called"] is False
    assert first["claims"]["live_money_enabled"] is False


def test_committed_phase_nine_evidence_is_current() -> None:
    root = Path(__file__).resolve().parents[1]

    assert check_multi_agent_artifacts(root) == ()
    assert phase_is_pass(root / "artifacts/governance/phase_gate_status.json", root, 9)
