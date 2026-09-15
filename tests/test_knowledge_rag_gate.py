from pathlib import Path

from aura.ops.knowledge_rag_gate import (
    build_retrieval_benchmark_report,
    check_knowledge_rag_artifacts,
)
from aura.ops.phase_gates import phase_is_pass


def test_phase_eight_report_is_deterministic_and_safe() -> None:
    first = build_retrieval_benchmark_report()
    second = build_retrieval_benchmark_report()

    assert first == second
    assert first["decision"] == "PASS"
    assert first["benchmark"]["top_1_accuracy"] == 1.0
    assert first["benchmark"]["mean_reciprocal_rank"] == 1.0
    assert all(first["safety_probes"].values())
    assert first["claims"]["copyrighted_material_scraped"] is False
    assert first["claims"]["live_money_enabled"] is False


def test_committed_phase_eight_evidence_is_current() -> None:
    root = Path(__file__).resolve().parents[1]

    assert check_knowledge_rag_artifacts(root) == ()
    assert phase_is_pass(root / "artifacts/governance/phase_gate_status.json", root, 8)
