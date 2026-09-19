from pathlib import Path

from aura.ops.backtest_gate import build_backtest_artifacts, check_backtest_artifacts
from aura.ops.phase_gates import phase_is_pass


def test_phase_six_proves_execution_parity_and_bias_guards() -> None:
    report, bias = build_backtest_artifacts()

    assert report["decision"] == "PASS"
    assert all(report["parity"].values())
    assert report["live_money_enabled"] is False
    assert bias["probes"]["future_dated_signal_blocked"] is True
    assert bias["probes"]["out_of_order_series_blocked"] is True
    assert bias["probes"]["fill_candle_index"] > bias["probes"]["signal_candle_index"]


def test_committed_phase_six_evidence_is_current() -> None:
    root = Path(__file__).resolve().parents[1]
    assert check_backtest_artifacts(root) == ()
    assert phase_is_pass(root / "artifacts/governance/phase_gate_status.json", root, 6)
