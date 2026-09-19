from pathlib import Path

from aura.ops.broker_conformance_gate import (
    build_broker_conformance_artifact,
    check_broker_conformance_artifact,
)
from aura.ops.phase_gates import phase_is_pass


def test_phase_four_report_is_truthful_and_strategy_isolated() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_broker_conformance_artifact(root)
    assert report["decision"] == "PASS"
    assert report["strategy_isolation"]["forbidden_imports"] == []
    assert report["mock_broker_contract_probe"]["passed"] is True
    assert report["credential_backed_validation_claimed"] is False
    assert report["live_money_enabled"] is False
    dhan = next(item for item in report["adapters"] if item["name"] == "DHAN_SANDBOX")
    assert dhan["supports_reconciliation"] is False


def test_committed_phase_four_evidence_is_current() -> None:
    root = Path(__file__).resolve().parents[1]
    assert check_broker_conformance_artifact(root) == ()
    assert phase_is_pass(root / "artifacts/governance/phase_gate_status.json", root, 4)
