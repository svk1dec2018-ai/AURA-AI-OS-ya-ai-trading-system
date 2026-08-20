from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aura.agents.service import MultiAgentDecisionService
from aura.data.pipeline import CandleDataPipeline, RawCandlePayload
from aura.data.quality import CandleQualityGate, DataQualityPolicy
from aura.ops.broker_conformance_gate import PHASE_FOUR_EVIDENCE
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.ops.risk_engine_gate import PHASE_THREE_EVIDENCE
from aura.ops.state_engine_gate import PHASE_TWO_EVIDENCE
from aura.runtime.scanner import MultiMarketIntelligenceScanner

OUTPUT_DIR = Path("artifacts/governance")
QUALITY_REPORT = OUTPUT_DIR / "data_quality_report.json"
ANOMALY_LOGS = OUTPUT_DIR / "anomaly_detection_logs.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_FIVE_EVIDENCE = {
    "Data quality report": QUALITY_REPORT.as_posix(),
    "Anomaly detection logs": ANOMALY_LOGS.as_posix(),
}

_START = datetime(2026, 1, 1, tzinfo=UTC)
_DECISION_TIME = _START + timedelta(minutes=3, seconds=30)


def _raw(minute: int, **updates: object) -> RawCandlePayload:
    start = _START + timedelta(minutes=minute)
    payload: dict[str, object] = {
        "symbol": " aura-phase5-fixture ",
        "venue": " internal_fixture ",
        "timeframe": "1M",
        "open_time": start,
        "close_time": start + timedelta(minutes=1),
        "open_price": "100",
        "high_price": "101",
        "low_price": "99",
        "close_price": "100.5",
        "volume": "10",
        "closed": True,
    }
    payload.update(updates)
    return RawCandlePayload.model_validate(payload)


def _pipeline() -> CandleDataPipeline:
    return CandleDataPipeline(
        CandleQualityGate(
            DataQualityPolicy(
                expected_interval=timedelta(minutes=1),
                max_staleness=timedelta(minutes=2),
                max_gap_multiple=2,
            )
        )
    )


def build_market_data_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline = _pipeline()
    accepted = pipeline.ingest(
        [_raw(0), _raw(1), _raw(2)],
        decision_time=_DECISION_TIME,
    )
    probes = {
        "normalization_error": pipeline.ingest(
            [_raw(0), _raw(1, high_price="98")],
            decision_time=_DECISION_TIME,
        ),
        "open_candle": pipeline.ingest(
            [_raw(0), _raw(1, closed=False)],
            decision_time=_DECISION_TIME,
        ),
        "duplicate_bar": pipeline.ingest(
            [_raw(0), _raw(0)],
            decision_time=_DECISION_TIME,
        ),
        "future_data": pipeline.ingest(
            [_raw(3)],
            decision_time=_DECISION_TIME,
        ),
        "stale": pipeline.ingest(
            [_raw(0)],
            decision_time=_DECISION_TIME,
        ),
    }
    if not accepted.accepted or accepted.validated is None:
        raise RuntimeError("valid normalized candle fixture did not pass the quality gate")
    if any(result.accepted for result in probes.values()):
        raise RuntimeError("a corrupt market-data probe escaped the quality gate")

    mandatory_boundaries = {
        "multi_agent_decision_service": _requires_quality_gate(MultiAgentDecisionService),
        "multi_market_intelligence_scanner": _requires_quality_gate(
            MultiMarketIntelligenceScanner
        ),
    }
    if not all(mandatory_boundaries.values()):
        raise RuntimeError("a decision boundary permits the data-quality gate to be omitted")

    anomaly_records = [
        {
            "probe": name,
            "accepted": result.accepted,
            "validated_candles_exposed": (
                len(result.validated.candles) if result.validated is not None else 0
            ),
            "anomaly_types": [item.anomaly_type for item in result.anomalies],
        }
        for name, result in sorted(probes.items())
    ]
    anomaly_log = {
        "schema_version": 1,
        "phase": 5,
        "decision": "PASS",
        "fixture_type": "deterministic_internal_data_fixture",
        "records": anomaly_records,
        "all_anomalous_batches_blocked": True,
        "external_market_data_claimed": False,
    }
    anomaly_log["deterministic_fingerprint"] = _sha256(anomaly_log)

    normalized = accepted.validated.candles
    report = {
        "schema_version": 1,
        "phase": 5,
        "decision": "PASS",
        "deliverables": {
            "data_ingestion": "aura.data.pipeline.CandleDataPipeline",
            "normalization_engine": "aura.data.normalization.normalize_candle",
            "quality_validation_layer": "aura.data.quality.CandleQualityGate",
        },
        "accepted_fixture": {
            "input_records": 3,
            "validated_records": len(normalized),
            "canonical_symbol": normalized[0].symbol,
            "canonical_venue": normalized[0].venue,
            "canonical_timeframe": normalized[0].timeframe,
            "latest_data_lag_ms": accepted.validated.quality.latest_data_lag_ms,
        },
        "decision_boundaries_require_quality_gate": mandatory_boundaries,
        "corrupt_batches_tested": len(probes),
        "corrupt_batches_blocked": sum(not item.accepted for item in probes.values()),
        "partial_batch_release_allowed": False,
        "external_market_data_claimed": False,
        "live_money_enabled": False,
    }
    report["deterministic_fingerprint"] = _sha256(report)
    return report, anomaly_log


def _requires_quality_gate(component: type[object]) -> bool:
    parameter = inspect.signature(component.__init__).parameters["data_quality_gate"]
    return parameter.default is inspect.Parameter.empty


def write_market_data_artifacts(root: Path) -> None:
    root = root.resolve()
    report, anomaly_log = build_market_data_artifacts()
    _write_json(root / QUALITY_REPORT, report)
    _write_json(root / ANOMALY_LOGS, anomaly_log)
    records = build_sequential_phase_records(
        root,
        {
            0: PHASE_ZERO_EVIDENCE,
            1: PHASE_ONE_EVIDENCE,
            2: PHASE_TWO_EVIDENCE,
            3: PHASE_THREE_EVIDENCE,
            4: PHASE_FOUR_EVIDENCE,
            5: PHASE_FIVE_EVIDENCE,
        },
    )
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_market_data_artifacts(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    report, anomaly_log = build_market_data_artifacts()
    expected = {
        QUALITY_REPORT: _pretty_json(report),
        ANOMALY_LOGS: _pretty_json(anomaly_log),
    }
    errors: list[str] = []
    for relative, content in expected.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing Phase 5 evidence: {relative.as_posix()}")
        elif path.read_text(encoding="utf-8") != content:
            errors.append(f"stale Phase 5 evidence: {relative.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 5):
        errors.append("Phase 5 is not PASS in the governance ledger")
    return tuple(errors)


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-5 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_market_data_artifacts(root)
        print("Phase 5: PASS")
        return 0
    errors = check_market_data_artifacts(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 5 market-data artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
