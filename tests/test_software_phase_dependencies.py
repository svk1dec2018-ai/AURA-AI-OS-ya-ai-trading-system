from __future__ import annotations

from pathlib import Path

from aura.ops.phase_gates import (
    GateDecision,
    PHASE_GATE_SPECS,
    build_sequential_phase_records,
    validate_phase_gate_records,
)


def _evidence(root: Path, phases: tuple[int, ...]) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    for phase in phases:
        spec = PHASE_GATE_SPECS[phase]
        outputs: dict[str, str] = {}
        for index, output in enumerate(spec.validation_outputs):
            relative = f"evidence/phase-{phase}-{index}.txt"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"phase={phase};output={output}\n", encoding="utf-8")
            outputs[output] = relative
        result[phase] = outputs
    return result


def test_phase_12_to_14_can_pass_while_external_phase_11_is_blocked(tmp_path: Path) -> None:
    phases = tuple(range(11)) + (12, 13, 14)
    records = build_sequential_phase_records(tmp_path, _evidence(tmp_path, phases))

    assert records[10].decision == GateDecision.PASS
    assert records[11].decision == GateDecision.BLOCKED
    assert records[12].decision == GateDecision.PASS
    assert records[13].decision == GateDecision.PASS
    assert records[14].decision == GateDecision.PASS
    assert records[15].decision == GateDecision.BLOCKED
    assert validate_phase_gate_records(records, tmp_path) == ()


def test_phase_13_requires_phase_12_even_when_phase_10_passes(tmp_path: Path) -> None:
    phases = tuple(range(11)) + (13,)
    records = build_sequential_phase_records(tmp_path, _evidence(tmp_path, phases))

    assert records[10].decision == GateDecision.PASS
    assert records[12].decision == GateDecision.BLOCKED
    assert records[13].decision == GateDecision.BLOCKED


def test_phase_15_remains_blocked_without_external_phase_11(tmp_path: Path) -> None:
    phases = tuple(range(11)) + (12, 13, 14, 15)
    records = build_sequential_phase_records(tmp_path, _evidence(tmp_path, phases))

    assert records[14].decision == GateDecision.PASS
    assert records[15].decision == GateDecision.BLOCKED
    assert any("11" in reason for reason in records[15].reasons)


def test_phase_15_can_only_pass_when_live_and_software_dependencies_pass(tmp_path: Path) -> None:
    phases = tuple(range(16))
    records = build_sequential_phase_records(tmp_path, _evidence(tmp_path, phases))

    assert all(record.decision == GateDecision.PASS for record in records)
    assert validate_phase_gate_records(records, tmp_path) == ()
