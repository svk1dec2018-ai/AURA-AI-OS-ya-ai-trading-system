from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from aura.execution.broker_evidence import (
    BrokerEvidenceAssessment,
    BrokerEvidenceVerifier,
    SealedBrokerEvidence,
    load_sealed_broker_attestation_registry,
    load_sealed_broker_evidence,
)


def assess_broker_evidence_files(
    evidence_paths: tuple[Path, ...],
    *,
    attestation_registry_path: Path | None = None,
) -> dict[str, Any]:
    """Validate offline evidence files without contacting or authorizing a broker."""

    normalized_paths = tuple(path.resolve() for path in evidence_paths)
    if len(set(normalized_paths)) != len(normalized_paths):
        raise ValueError("duplicate broker evidence input path")

    evidence: tuple[SealedBrokerEvidence, ...] = tuple(
        load_sealed_broker_evidence(path) for path in normalized_paths
    )
    registry_sha256: str | None = None
    if attestation_registry_path is None:
        verifier = BrokerEvidenceVerifier()
    else:
        sealed_registry = load_sealed_broker_attestation_registry(
            attestation_registry_path.resolve()
        )
        registry_sha256 = sealed_registry.sha256
        verifier = BrokerEvidenceVerifier(
            attestation_verifier=sealed_registry.registry.verifies
        )

    assessment = verifier.assess(evidence)
    return _report(
        evidence=evidence,
        assessment=assessment,
        registry_sha256=registry_sha256,
    )


def _report(
    *,
    evidence: tuple[SealedBrokerEvidence, ...],
    assessment: BrokerEvidenceAssessment,
    registry_sha256: str | None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "phase": 11,
        "intake_decision": (
            "ELIGIBLE_FOR_GATE_REVIEW" if assessment.phase11_eligible else "BLOCKED"
        ),
        "eligibility_candidate": assessment.phase11_eligible,
        "phase_gate_updated": False,
        "phase11_pass_claimed": False,
        "execution_authority": False,
        "broker_connection_performed": False,
        "evidence_bundle_sha256": sorted(item.sha256 for item in evidence),
        "attestation_registry_sha256": registry_sha256,
        "assessment": assessment.model_dump(mode="json"),
    }
    report["report_sha256"] = _sha256(report)
    return report


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline, credential-free Phase 11 broker evidence intake"
    )
    parser.add_argument("--evidence", action="append", default=[], type=Path)
    parser.add_argument("--attestation-registry", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--require-eligible",
        action="store_true",
        help="return non-zero when the validated evidence remains blocked",
    )
    args = parser.parse_args()

    report = assess_broker_evidence_files(
        tuple(args.evidence),
        attestation_registry_path=args.attestation_registry,
    )
    _write_report(args.output, report)
    print(
        f"Phase 11 evidence intake: {report['intake_decision']}; "
        "execution authority remains disabled"
    )
    if args.require_eligible and not report["eligibility_candidate"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
