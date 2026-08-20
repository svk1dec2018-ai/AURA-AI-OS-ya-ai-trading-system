from __future__ import annotations

import hashlib
from pathlib import Path

from aura.ops.phase_gates import (
    PHASE_GATE_SPECS,
    GateDecision,
    GateEvidence,
    PhaseGateRecord,
    phase_is_pass,
    validate_phase_gate_ledger,
    validate_phase_gate_records,
    write_phase_gate_ledger,
)


def _evidence(path: Path, output: str) -> GateEvidence:
    return GateEvidence(
        output=output,
        path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def test_all_phase_specs_have_complete_non_skippable_contracts() -> None:
    assert tuple(spec.phase for spec in PHASE_GATE_SPECS) == tuple(range(16))
    assert all(spec.deliverables for spec in PHASE_GATE_SPECS)
    assert all(spec.success_criteria for spec in PHASE_GATE_SPECS)
    assert all(spec.validation_outputs for spec in PHASE_GATE_SPECS)
    assert all(spec.stop_condition for spec in PHASE_GATE_SPECS)


def test_later_phase_cannot_pass_before_previous_phase(tmp_path) -> None:
    artifact = tmp_path / "evidence.txt"
    artifact.write_text("evidence", encoding="utf-8")
    records = [
        PhaseGateRecord(0, GateDecision.BLOCKED, reasons=("audit pending",)),
        PhaseGateRecord(
            1,
            GateDecision.PASS,
            evidence=tuple(
                _evidence(artifact, output)
                for output in PHASE_GATE_SPECS[1].validation_outputs
            ),
        ),
    ]
    records.extend(
        PhaseGateRecord(
            phase,
            GateDecision.BLOCKED,
            reasons=("prior phase has not passed",),
        )
        for phase in range(2, 16)
    )

    errors = validate_phase_gate_records(records, tmp_path)
    assert "phase 1 cannot PASS before phase 0" in errors


def test_phase_gate_evidence_hash_is_tamper_evident(tmp_path) -> None:
    artifact = tmp_path / "evidence.txt"
    artifact.write_text("original", encoding="utf-8")
    records = tuple(
        PhaseGateRecord(
            spec.phase,
            GateDecision.PASS,
            evidence=tuple(
                _evidence(artifact, output) for output in spec.validation_outputs
            ),
        )
        for spec in PHASE_GATE_SPECS
    )
    path = tmp_path / "artifacts" / "governance" / "phase_gate_status.json"
    write_phase_gate_ledger(path, records)
    assert validate_phase_gate_ledger(path, tmp_path) == ()

    artifact.write_text("tampered", encoding="utf-8")
    errors = validate_phase_gate_ledger(path, tmp_path)
    assert any("evidence hash mismatch" in error for error in errors)
    assert phase_is_pass(path, tmp_path, 15) is False


def test_committed_ledger_passes_through_market_data_only() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "artifacts" / "governance" / "phase_gate_status.json"
    assert validate_phase_gate_ledger(path, root) == ()
    assert phase_is_pass(path, root, 0) is True
    assert phase_is_pass(path, root, 1) is True
    assert phase_is_pass(path, root, 2) is True
    assert phase_is_pass(path, root, 3) is True
    assert phase_is_pass(path, root, 4) is True
    assert phase_is_pass(path, root, 5) is True
    assert phase_is_pass(path, root, 6) is False
    assert phase_is_pass(path, root, 15) is False
