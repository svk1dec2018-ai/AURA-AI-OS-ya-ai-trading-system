from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class GateDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


@dataclass(slots=True, frozen=True)
class PhaseGateSpec:
    phase: int
    name: str
    deliverables: tuple[str, ...]
    success_criteria: tuple[str, ...]
    validation_outputs: tuple[str, ...]
    stop_condition: str

    def __post_init__(self) -> None:
        if self.phase < 0 or self.phase > 15:
            raise ValueError("phase must be in [0, 15]")
        if not self.name.strip():
            raise ValueError("phase name is required")
        if not self.deliverables or not self.success_criteria or not self.validation_outputs:
            raise ValueError("every phase requires deliverables, criteria and validation outputs")
        if not self.stop_condition.strip():
            raise ValueError("every phase requires a stop condition")


@dataclass(slots=True, frozen=True)
class GateEvidence:
    output: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.output.strip() or not self.path.strip():
            raise ValueError("evidence output and path are required")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError("evidence sha256 must be lowercase hexadecimal")


@dataclass(slots=True, frozen=True)
class PhaseGateRecord:
    phase: int
    decision: GateDecision
    evidence: tuple[GateEvidence, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.phase < 0 or self.phase > 15:
            raise ValueError("phase must be in [0, 15]")
        if self.decision != GateDecision.PASS and not self.reasons:
            raise ValueError("FAIL and BLOCKED phase records require reasons")


PHASE_GATE_SPECS: tuple[PhaseGateSpec, ...] = (
    PhaseGateSpec(
        0,
        "Repository audit and baseline",
        ("Full repository structure map", "Module inventory", "Dependency graph", "Test discovery report", "Stub and broken-code list"),
        ("100% of modules are classified", "All entrypoints are identified", "No unknown components remain"),
        ("repo_audit.json", "module_map.md", "test_inventory.json"),
        "If any module is unclassified, the phase fails.",
    ),
    PhaseGateSpec(
        1,
        "Core data contracts",
        ("Unified Tick, Candle, Order, Fill, Position and portfolio models", "Typed schemas", "Serialization layer"),
        ("All core entities pass schema tests", "No ambiguous schema fields remain"),
        ("Schema test report", "Contract validation suite"),
        "Any missing core entity blocks the phase.",
    ),
    PhaseGateSpec(
        2,
        "Portfolio and order state engine",
        ("Portfolio state manager", "Order lifecycle state machine", "Fill reconciliation logic"),
        ("State transitions are deterministic", "Restart recovery passes"),
        ("State transition logs", "Reconciliation test report"),
        "Any broker/internal state mismatch fails the phase.",
    ),
    PhaseGateSpec(
        3,
        "Risk engine",
        ("Risk rules engine", "Position sizing engine", "Portfolio exposure controls", "Kill switch logic"),
        ("Risk veto always overrides a trade", "Outputs are fully deterministic"),
        ("Risk stress test report", "Violation simulation logs"),
        "Any risk-engine bypass immediately fails the phase.",
    ),
    PhaseGateSpec(
        4,
        "Broker abstraction layer",
        ("Broker interface", "Angel One adapter", "MT5 adapter skeleton", "Reconciliation system"),
        ("Broker swaps do not affect strategies", "Adapter conformance tests pass"),
        ("Adapter conformance report",),
        "Broker-specific logic in a strategy fails the phase.",
    ),
    PhaseGateSpec(
        5,
        "Market data pipeline",
        ("Data ingestion", "Normalization engine", "Quality validation layer"),
        ("Corrupt data cannot reach strategies", "Data lag is measured"),
        ("Data quality report", "Anomaly detection logs"),
        "Any unvalidated data entering the pipeline fails the phase.",
    ),
    PhaseGateSpec(
        6,
        "Backtest engine",
        ("Unified backtest/live engine", "Slippage model", "Cost model"),
        ("Backtest uses live execution logic", "Look-ahead bias checks pass"),
        ("Backtest report", "Bias detection report"),
        "Any backtest/live divergence fails the phase.",
    ),
    PhaseGateSpec(
        7,
        "Strategy research lab",
        ("Strategy factory", "Hypothesis generator", "Evaluation engine"),
        ("Strategies are reproducible", "Overfitting controls pass"),
        ("Strategy evaluation report",),
        "Promotion of any untested strategy fails the phase.",
    ),
    PhaseGateSpec(
        8,
        "Knowledge and RAG engine",
        ("Document ingestion", "Retrieval engine", "Metadata tagging"),
        ("Retrieval benchmark passes", "No hallucinated knowledge is used"),
        ("Retrieval benchmark report",),
        "Use of unverified knowledge in trading fails the phase.",
    ),
    PhaseGateSpec(
        9,
        "Multi-agent system",
        ("Specialist agents", "Structured output schema", "Agent registry"),
        ("Agent outputs are deterministic and structured", "No free-form authority path exists"),
        ("Agent consistency report",),
        "Any agent bypassing its schema fails the phase.",
    ),
    PhaseGateSpec(
        10,
        "CEO decision engine",
        ("Evidence fusion", "Decision aggregation", "Explainability layer"),
        ("Decisions are reproducible", "Decision outputs are explainable"),
        ("Decision trace logs",),
        "Any non-reproducible decision fails the phase.",
    ),
    PhaseGateSpec(
        11,
        "Broker integration live readiness",
        ("Angel One integration", "MT5 integration"),
        ("Order execution is externally verified", "Reconciliation is stable"),
        ("Live execution logs",),
        "Any unverified order execution fails the phase.",
    ),
    PhaseGateSpec(
        12,
        "Paper trading system",
        ("Simulated execution engine", "Live-data paper mode"),
        ("Paper behavior is demonstrably identical to the live engine"),
        ("Paper versus live parity report",),
        "Any behavior mismatch fails the phase.",
    ),
    PhaseGateSpec(
        13,
        "Alerting, UI and voice",
        ("Alert system", "Dashboard", "Voice interface"),
        ("Updates are real-time", "No critical alerts are missed"),
        ("Alert delivery logs",),
        "Any missed critical event fails the phase.",
    ),
    PhaseGateSpec(
        14,
        "End-to-end system validation",
        ("Full-system simulation", "Chaos test suite"),
        ("The system survives tested failures", "No data corruption occurs"),
        ("Full system audit report",),
        "Any critical failure fails the phase.",
    ),
    PhaseGateSpec(
        15,
        "Controlled live deployment readiness",
        ("Production readiness report", "Risk certification", "Monitoring dashboard"),
        ("Every earlier phase is PASS", "Zero critical issues remain"),
        ("Final readiness certificate",),
        "Any unresolved risk blocks live deployment.",
    ),
)


def build_phase_zero_records(
    root: Path,
    evidence_paths: Mapping[str, str],
) -> tuple[PhaseGateRecord, ...]:
    required = set(PHASE_GATE_SPECS[0].validation_outputs)
    if set(evidence_paths) != required:
        raise ValueError("phase 0 evidence must exactly match its required outputs")
    evidence = tuple(
        GateEvidence(output, path, _file_sha256(_resolve_evidence_path(root, path)))
        for output, path in sorted(evidence_paths.items())
    )
    records = [PhaseGateRecord(0, GateDecision.PASS, evidence=evidence)]
    for spec in PHASE_GATE_SPECS[1:]:
        previous = PHASE_GATE_SPECS[spec.phase - 1]
        reason = (
            f"Phase {spec.phase} validation evidence has not been produced or accepted; "
            f"Phase {previous.phase} must remain PASS before this gate can pass."
        )
        records.append(
            PhaseGateRecord(
                spec.phase,
                GateDecision.BLOCKED,
                reasons=(reason,),
            )
        )
    return tuple(records)


def validate_phase_gate_records(
    records: Iterable[PhaseGateRecord],
    root: Path,
) -> tuple[str, ...]:
    ordered = tuple(records)
    errors: list[str] = []
    if tuple(record.phase for record in ordered) != tuple(range(16)):
        return ("phase records must contain each phase 0..15 exactly once in order",)

    for spec, record in zip(PHASE_GATE_SPECS, ordered):
        if record.decision == GateDecision.PASS:
            if record.phase > 0 and ordered[record.phase - 1].decision != GateDecision.PASS:
                errors.append(f"phase {record.phase} cannot PASS before phase {record.phase - 1}")
            supplied = {item.output: item for item in record.evidence}
            if len(supplied) != len(record.evidence):
                errors.append(f"phase {record.phase} contains duplicate evidence outputs")
            missing = set(spec.validation_outputs) - set(supplied)
            unexpected = set(supplied) - set(spec.validation_outputs)
            if missing:
                errors.append(f"phase {record.phase} is missing evidence: {sorted(missing)}")
            if unexpected:
                errors.append(
                    f"phase {record.phase} contains unexpected evidence: {sorted(unexpected)}"
                )
            for item in record.evidence:
                try:
                    path = _resolve_evidence_path(root, item.path)
                except ValueError as exc:
                    errors.append(f"phase {record.phase} evidence path invalid: {exc}")
                    continue
                if not path.is_file():
                    errors.append(f"phase {record.phase} evidence file missing: {item.path}")
                elif _file_sha256(path) != item.sha256:
                    errors.append(f"phase {record.phase} evidence hash mismatch: {item.path}")
        elif not record.reasons:
            errors.append(f"phase {record.phase} {record.decision.value} has no reason")
    return tuple(errors)


def write_phase_gate_ledger(
    path: Path,
    records: Iterable[PhaseGateRecord],
    *,
    root: Path | None = None,
) -> None:
    ordered = tuple(records)
    repository_root = root or path.parent.parent.parent
    errors = validate_phase_gate_records(ordered, repository_root)
    if errors:
        raise ValueError("invalid phase gate ledger: " + "; ".join(errors))
    payload = _ledger_payload(ordered)
    envelope = {
        **payload,
        "ledger_sha256": _json_sha256(payload),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_phase_gate_ledger(path: Path, root: Path) -> tuple[str, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (f"phase gate ledger unreadable: {exc}",)
    supplied_hash = raw.pop("ledger_sha256", None)
    errors: list[str] = []
    if supplied_hash != _json_sha256(raw):
        errors.append("phase gate ledger hash mismatch")
    canonical_specs = json.loads(json.dumps([asdict(spec) for spec in PHASE_GATE_SPECS]))
    if raw.get("specs") != canonical_specs:
        errors.append("phase gate specifications do not match the canonical policy")
    if raw.get("schema_version") != 1:
        errors.append("unsupported phase gate ledger schema version")
    try:
        records = tuple(
            PhaseGateRecord(
                phase=int(item["phase"]),
                decision=GateDecision(item["decision"]),
                evidence=tuple(GateEvidence(**evidence) for evidence in item.get("evidence", [])),
                reasons=tuple(item.get("reasons", [])),
            )
            for item in raw["records"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        return tuple(errors) + (f"phase gate ledger schema invalid: {exc}",)
    errors.extend(validate_phase_gate_records(records, root))
    return tuple(errors)


def phase_is_pass(path: Path, root: Path, phase: int) -> bool:
    if phase < 0 or phase > 15 or validate_phase_gate_ledger(path, root):
        return False
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["records"][phase]["decision"] == GateDecision.PASS.value


def _ledger_payload(records: tuple[PhaseGateRecord, ...]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "policy": "AURA mandatory sequential phase gates 0-15",
        "specs": [asdict(spec) for spec in PHASE_GATE_SPECS],
        "records": [
            {
                "phase": record.phase,
                "decision": record.decision.value,
                "evidence": [asdict(item) for item in record.evidence],
                "reasons": list(record.reasons),
            }
            for record in records
        ],
    }


def _resolve_evidence_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if not candidate.is_relative_to(resolved_root):
        raise ValueError(f"evidence escapes repository root: {relative}")
    return candidate


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
