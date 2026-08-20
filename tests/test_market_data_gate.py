from pathlib import Path

from aura.ops.market_data_gate import (
    build_market_data_artifacts,
    check_market_data_artifacts,
)
from aura.ops.phase_gates import phase_is_pass


def test_phase_five_probes_block_every_anomalous_batch() -> None:
    report, anomaly_log = build_market_data_artifacts()

    assert report["decision"] == "PASS"
    assert report["corrupt_batches_tested"] == report["corrupt_batches_blocked"]
    assert report["accepted_fixture"]["latest_data_lag_ms"] == 30000
    assert all(not record["accepted"] for record in anomaly_log["records"])
    assert all(record["validated_candles_exposed"] == 0 for record in anomaly_log["records"])


def test_committed_phase_five_evidence_is_current() -> None:
    root = Path(__file__).resolve().parents[1]
    assert check_market_data_artifacts(root) == ()
    assert phase_is_pass(root / "artifacts/governance/phase_gate_status.json", root, 5)
