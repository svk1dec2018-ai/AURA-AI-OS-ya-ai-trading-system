from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aura.domain.models import OrderStatus
from aura.execution.broker import BrokerExecutionMode
from aura.execution.broker_evidence import (
    BrokerAttestationRegistry,
    BrokerAttestationReview,
    BrokerEvidenceBundle,
    BrokerEvidenceSource,
    BrokerExecutionObservation,
    BrokerReconciliationObservation,
    SealedBrokerAttestationRegistry,
    SealedBrokerEvidence,
)
from aura.ops.broker_evidence_intake import assess_broker_evidence_files, main

_START = datetime(2026, 8, 21, 4, 0, tzinfo=UTC)


def _bundle(adapter: str) -> BrokerEvidenceBundle:
    execution = BrokerExecutionObservation(
        probe_id=f"{adapter}:probe",
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
    reconciliation = tuple(
        BrokerReconciliationObservation(
            run_id=f"{adapter}:reconciliation:{index}",
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
        capture_id=f"{adapter}:capture",
        adapter_name=adapter,
        mode=BrokerExecutionMode.CONTROLLED_LIVE,
        source=BrokerEvidenceSource.AUTHORIZED_EXTERNAL_BROKER,
        environment_verified=True,
        account_fingerprint="d" * 64,
        attestation_fingerprint="e" * 64,
        captured_at=_START + timedelta(minutes=1),
        executions=(execution,),
        reconciliation_runs=reconciliation,
    )


def _registry(evidence: tuple[SealedBrokerEvidence, ...]) -> BrokerAttestationRegistry:
    reviews = tuple(
        BrokerAttestationReview(
            bundle_sha256=item.sha256,
            reviewer_fingerprint=reviewer * 64,
            reviewed_at=_START + timedelta(minutes=2 + index),
        )
        for item in evidence
        for index, reviewer in enumerate(("1", "2"))
    )
    return BrokerAttestationRegistry(
        registry_id="owner-reviewed-phase11-evidence",
        generated_at=_START + timedelta(minutes=10),
        reviews=reviews,
    )


def _write_json(path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def test_intake_requires_review_quorum_and_never_updates_gate(tmp_path) -> None:
    evidence = tuple(
        SealedBrokerEvidence.seal(_bundle(adapter))
        for adapter in ("ANGEL_ONE_SMARTAPI", "MT5")
    )
    evidence_paths = tuple(tmp_path / f"evidence-{index}.json" for index in range(2))
    for path, item in zip(evidence_paths, evidence, strict=True):
        _write_json(path, item.model_dump(mode="json"))

    blocked = assess_broker_evidence_files(evidence_paths)
    assert blocked["intake_decision"] == "BLOCKED"
    assert blocked["eligibility_candidate"] is False

    one_review_each = BrokerAttestationRegistry(
        registry_id="insufficient-review-quorum",
        generated_at=_START + timedelta(minutes=10),
        reviews=tuple(
            BrokerAttestationReview(
                bundle_sha256=item.sha256,
                reviewer_fingerprint="1" * 64,
                reviewed_at=_START + timedelta(minutes=2),
            )
            for item in evidence
        ),
    )
    insufficient_path = tmp_path / "insufficient-registry.json"
    _write_json(
        insufficient_path,
        SealedBrokerAttestationRegistry.seal(one_review_each).model_dump(mode="json"),
    )
    insufficient = assess_broker_evidence_files(
        evidence_paths,
        attestation_registry_path=insufficient_path,
    )
    assert insufficient["intake_decision"] == "BLOCKED"
    assert insufficient["eligibility_candidate"] is False

    sealed_registry = SealedBrokerAttestationRegistry.seal(_registry(evidence))
    registry_path = tmp_path / "registry.json"
    _write_json(registry_path, sealed_registry.model_dump(mode="json"))
    report = assess_broker_evidence_files(
        evidence_paths,
        attestation_registry_path=registry_path,
    )

    assert report["intake_decision"] == "ELIGIBLE_FOR_GATE_REVIEW"
    assert report["eligibility_candidate"] is True
    assert report["phase_gate_updated"] is False
    assert report["phase11_pass_claimed"] is False
    assert report["execution_authority"] is False
    assert report["broker_connection_performed"] is False


def test_registry_rejects_duplicate_review_and_future_review() -> None:
    evidence = (SealedBrokerEvidence.seal(_bundle("MT5")),)
    review = BrokerAttestationReview(
        bundle_sha256=evidence[0].sha256,
        reviewer_fingerprint="1" * 64,
        reviewed_at=_START + timedelta(minutes=2),
    )
    with pytest.raises(ValidationError, match="duplicate broker attestation review"):
        BrokerAttestationRegistry(
            registry_id="duplicate",
            generated_at=_START + timedelta(minutes=3),
            reviews=(review, review),
        )

    with pytest.raises(ValidationError, match="after registry generation"):
        BrokerAttestationRegistry(
            registry_id="future",
            generated_at=_START + timedelta(minutes=1),
            reviews=(review,),
        )


def test_registry_is_content_addressed(tmp_path) -> None:
    evidence = (SealedBrokerEvidence.seal(_bundle("MT5")),)
    sealed = SealedBrokerAttestationRegistry.seal(_registry(evidence))
    payload = sealed.model_dump(mode="json")
    payload["registry"]["registry_id"] = "tampered"
    path = tmp_path / "registry.json"
    _write_json(path, payload)

    with pytest.raises(ValidationError, match="registry content hash mismatch"):
        assess_broker_evidence_files((), attestation_registry_path=path)


def test_registry_loader_rejects_secret_fields(tmp_path) -> None:
    evidence = (SealedBrokerEvidence.seal(_bundle("MT5")),)
    payload = SealedBrokerAttestationRegistry.seal(_registry(evidence)).model_dump(
        mode="json"
    )
    payload["registry"]["api_key"] = "must-not-be-stored"
    path = tmp_path / "registry.json"
    _write_json(path, payload)

    with pytest.raises(ValueError, match="forbidden secret field"):
        assess_broker_evidence_files((), attestation_registry_path=path)


def test_cli_writes_blocked_report_and_optional_gate_exit(tmp_path, monkeypatch) -> None:
    output = tmp_path / "intake.json"
    monkeypatch.setattr(
        "sys.argv",
        ["broker-evidence-intake", "--output", str(output), "--require-eligible"],
    )

    assert main() == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["intake_decision"] == "BLOCKED"
    assert report["evidence_bundle_sha256"] == []
    assert report["phase_gate_updated"] is False
