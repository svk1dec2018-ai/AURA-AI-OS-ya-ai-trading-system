from pathlib import Path

from aura.ops.phase_gates import phase_is_pass
from aura.ops.strategy_research_gate import (
    build_strategy_evaluation_report,
    check_strategy_research_artifacts,
)


def test_phase_seven_report_is_reproducible_and_fail_closed() -> None:
    first = build_strategy_evaluation_report()
    second = build_strategy_evaluation_report()

    assert first == second
    assert first["decision"] == "PASS"
    assert all(first["reproducibility"].values())
    assert first["overfitting_controls"]["overfit_candidate_rejected"] is True
    assert first["promotion_controls"]["untested_promotion_blocked"] is True
    assert first["claims"]["strategy_performance_claimed"] is False
    assert first["claims"]["live_money_enabled"] is False


def test_committed_phase_seven_evidence_is_current() -> None:
    root = Path(__file__).resolve().parents[1]

    assert check_strategy_research_artifacts(root) == ()
    assert phase_is_pass(root / "artifacts/governance/phase_gate_status.json", root, 7)
