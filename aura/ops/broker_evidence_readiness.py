from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from aura.domain.models import OrderStatus
from aura.execution.angel_one import AngelOneReadOnlyBroker
from aura.execution.broker import BrokerExecutionMode
from aura.execution.broker_evidence import (
    BrokerEvidenceBundle,
    BrokerEvidenceSource,
    BrokerEvidenceVerifier,
    BrokerExecutionObservation,
    BrokerReconciliationObservation,
    SealedBrokerEvidence,
)
from aura.execution.mt5_demo_broker import MT5DemoBroker
from aura.ops.phase_gates import phase_is_pass, validate_phase_gate_ledger

OUTPUT_DIR = Path("artifacts/governance")
READINESS_REPORT = OUTPUT_DIR / "broker_evidence_readiness_report.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"

_START = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)


def build_broker_evidence_readiness_report() -> dict[str, Any]:
    verifier = BrokerEvidenceVerifier()
    missing = verifier.assess(())
    internal_fixture = verifier.assess(
        (
            SealedBrokerEvidence.seal(_fixture_bundle("ANGEL_ONE_SMARTAPI")),
            SealedBrokerEvidence.seal(_fixture_bundle("MT5")),
        )
    )
    self_asserted_external = verifier.assess(
        (
            SealedBrokerEvidence.seal(
                _fixture_bundle(
                    "ANGEL_ONE_SMARTAPI",
                    source=BrokerEvidenceSource.AUTHORIZED_EXTERNAL_BROKER,
                )
            ),
            SealedBrokerEvidence.seal(
                _fixture_bundle(
                    "MT5",
                    source=BrokerEvidenceSource.AUTHORIZED_EXTERNAL_BROKER,
                )
            ),
        )
    )
    probes = {
        "missing_evidence_is_blocked": not missing.phase11_eligible,
        "internal_fixture_is_not_external_proof": not internal_fixture.phase11_eligible,
        "self_asserted_source_without_attestation_is_blocked": (
            not self_asserted_external.phase11_eligible
        ),
        "angel_one_execution_remains_locked": (
            AngelOneReadOnlyBroker.capabilities.mode == BrokerExecutionMode.READ_ONLY
            and not AngelOneReadOnlyBroker.capabilities.supports_order_submission
            and not AngelOneReadOnlyBroker.capabilities.live_money_enabled
        ),
        "mt5_remains_verified_demo_only": (
            MT5DemoBroker.capabilities.mode == BrokerExecutionMode.DEMO
            and MT5DemoBroker.capabilities.supports_order_submission
            and not MT5DemoBroker.capabilities.live_money_enabled
        ),
    }
    if not all(probes.values()):
        raise RuntimeError("Phase 11 broker evidence readiness probe failed")

    report: dict[str, Any] = {
        "schema_version": 1,
        "phase": 11,
        "gate_decision": "BLOCKED",
        "increment_status": "EVIDENCE_VALIDATOR_READY",
        "fixture_type": "deterministic_internal_broker_evidence_fixture",
        "current_adapters": {
            "ANGEL_ONE_SMARTAPI": _capabilities(AngelOneReadOnlyBroker),
            "MT5": _capabilities(MT5DemoBroker),
        },
        "validation_probes": probes,
        "blocked_assessments": {
            "no_evidence": missing.model_dump(mode="json"),
            "internal_fixture": internal_fixture.model_dump(mode="json"),
            "self_asserted_external_without_attestation": (
                self_asserted_external.model_dump(mode="json")
            ),
        },
        "exact_external_blockers": [
            "Angel One remains read-only until separately authorized controlled-live implementation and canary evidence exist.",
            "MT5 execution is verified only against a DEMO account; no controlled-live adapter evidence exists.",
            "No cryptographically or operator-verified external broker attestation verifier is configured.",
            "No authorized external normalized fill evidence has been supplied for both required adapters.",
            "No minimum sequence of three clean external reconciliation observations has been supplied for both required adapters.",
            "No separate owner financial-risk authorization has been supplied; code approval is not trade approval.",
        ],
        "authority_boundary": {
            "validator_can_connect_to_broker": False,
            "validator_can_submit_orders": False,
            "validator_can_enable_live_money": False,
            "validator_can_bypass_risk": False,
        },
        "claims": {
            "external_broker_called": False,
            "external_execution_verified": False,
            "trading_action_performed": False,
            "live_money_enabled": False,
            "phase11_pass_claimed": False,
        },
    }
    report["deterministic_fingerprint"] = _sha256(report)
    return report


def _fixture_bundle(
    adapter_name: str,
    *,
    source: BrokerEvidenceSource = BrokerEvidenceSource.INTERNAL_FIXTURE,
) -> BrokerEvidenceBundle:
    execution = BrokerExecutionObservation(
        probe_id=f"fixture:{adapter_name}:execution",
        client_order_fingerprint="a" * 64,
        broker_order_fingerprint="b" * 64,
        broker_response_fingerprint="c" * 64,
        requested_quantity=Decimal(1),
        filled_quantity=Decimal(1),
        fill_count=1,
        final_status=OrderStatus.FILLED,
        submitted_at=_START,
        acknowledged_at=_START + timedelta(seconds=1),
        final_observed_at=_START + timedelta(seconds=2),
    )
    reconciliations = tuple(
        BrokerReconciliationObservation(
            run_id=f"fixture:{adapter_name}:reconciliation:{index}",
            observed_at=_START + timedelta(seconds=10 + index),
            local_open_orders=0,
            broker_open_orders=0,
            compared_positions=1,
            issue_count=0,
            critical_issue_count=0,
            safe_for_new_risk=True,
            report_fingerprint=f"{index + 1:064x}",
        )
        for index in range(3)
    )
    return BrokerEvidenceBundle(
        capture_id=f"fixture:{adapter_name}:{source.value}",
        adapter_name=adapter_name,
        mode=BrokerExecutionMode.CONTROLLED_LIVE,
        source=source,
        environment_verified=True,
        account_fingerprint="d" * 64,
        attestation_fingerprint="e" * 64,
        captured_at=_START + timedelta(minutes=1),
        executions=(execution,),
        reconciliation_runs=reconciliations,
    )


def _capabilities(adapter: type[Any]) -> dict[str, Any]:
    capabilities = adapter.capabilities
    return {
        "implementation": f"{adapter.__module__}.{adapter.__qualname__}",
        "mode": capabilities.mode.value,
        "supports_order_submission": capabilities.supports_order_submission,
        "supports_order_cancellation": capabilities.supports_order_cancellation,
        "supports_fill_stream": capabilities.supports_fill_stream,
        "supports_reconciliation": capabilities.supports_reconciliation,
        "live_money_enabled": capabilities.live_money_enabled,
    }


def write_broker_evidence_readiness(root: Path) -> None:
    root = root.resolve()
    _write_json(root / READINESS_REPORT, build_broker_evidence_readiness_report())


def check_broker_evidence_readiness(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    expected = _pretty_json(build_broker_evidence_readiness_report())
    path = root / READINESS_REPORT
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"missing Phase 11 readiness evidence: {READINESS_REPORT.as_posix()}")
    elif path.read_text(encoding="utf-8") != expected:
        errors.append(f"stale Phase 11 readiness evidence: {READINESS_REPORT.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 10):
        errors.append("Phase 10 must remain PASS before Phase 11 readiness work")
    if not errors and phase_is_pass(root / PHASE_LEDGER, root, 11):
        errors.append("Phase 11 must remain BLOCKED without accepted external evidence")
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
    parser = argparse.ArgumentParser(
        description="Generate or verify AURA Phase-11 broker evidence readiness"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_broker_evidence_readiness(root)
        print("Phase 11 readiness: validator ready; gate remains BLOCKED")
        return 0
    errors = check_broker_evidence_readiness(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 11 broker evidence readiness artifact is current and BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
