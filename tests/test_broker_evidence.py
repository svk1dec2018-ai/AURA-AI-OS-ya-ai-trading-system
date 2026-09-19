from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aura.domain.models import OrderStatus
from aura.execution.broker import BrokerExecutionMode
from aura.execution.broker_evidence import (
    BrokerEvidenceBundle,
    BrokerEvidenceSource,
    BrokerEvidenceVerifier,
    BrokerExecutionObservation,
    BrokerReconciliationObservation,
    SealedBrokerEvidence,
    load_sealed_broker_evidence,
)

_START = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)
_HASH = "a" * 64


def _execution() -> BrokerExecutionObservation:
    return BrokerExecutionObservation(
        probe_id="external-probe-1",
        client_order_fingerprint="b" * 64,
        broker_order_fingerprint="c" * 64,
        broker_response_fingerprint="d" * 64,
        requested_quantity=Decimal(1),
        filled_quantity=Decimal(1),
        fill_count=1,
        final_status=OrderStatus.FILLED,
        submitted_at=_START,
        acknowledged_at=_START + timedelta(seconds=1),
        final_observed_at=_START + timedelta(seconds=2),
    )


def _reconciliation(index: int) -> BrokerReconciliationObservation:
    return BrokerReconciliationObservation(
        run_id=f"reconcile-{index}",
        observed_at=_START + timedelta(seconds=10 + index),
        local_open_orders=0,
        broker_open_orders=0,
        compared_positions=1,
        issue_count=0,
        critical_issue_count=0,
        safe_for_new_risk=True,
        report_fingerprint=f"{index + 1:064x}",
    )


def _bundle(
    adapter_name: str,
    *,
    source: BrokerEvidenceSource = BrokerEvidenceSource.AUTHORIZED_EXTERNAL_BROKER,
    mode: BrokerExecutionMode = BrokerExecutionMode.CONTROLLED_LIVE,
    capture_suffix: str = "",
) -> BrokerEvidenceBundle:
    return BrokerEvidenceBundle(
        capture_id=f"capture:{adapter_name}{capture_suffix}",
        adapter_name=adapter_name,
        mode=mode,
        source=source,
        environment_verified=True,
        account_fingerprint=_HASH,
        attestation_fingerprint="e" * 64,
        captured_at=_START + timedelta(minutes=1),
        executions=(_execution(),),
        reconciliation_runs=tuple(_reconciliation(index) for index in range(3)),
    )


def test_sealed_broker_evidence_is_content_addressed() -> None:
    sealed = SealedBrokerEvidence.seal(_bundle("MT5"))
    assert len(sealed.sha256) == 64

    with pytest.raises(ValidationError, match="content hash mismatch"):
        SealedBrokerEvidence(bundle=sealed.bundle, sha256="0" * 64)


def test_internal_or_demo_fixture_cannot_pass_phase11() -> None:
    verifier = BrokerEvidenceVerifier()
    internal = verifier.assess(
        (
            SealedBrokerEvidence.seal(
                _bundle(
                    "ANGEL_ONE_SMARTAPI",
                    source=BrokerEvidenceSource.INTERNAL_FIXTURE,
                )
            ),
            SealedBrokerEvidence.seal(
                _bundle("MT5", source=BrokerEvidenceSource.INTERNAL_FIXTURE)
            ),
        )
    )
    assert internal.gate_decision == "BLOCKED"
    assert not internal.phase11_eligible
    assert any("authorized external" in reason for reason in internal.reasons)

    demo = verifier.assess(
        (
            SealedBrokerEvidence.seal(_bundle("ANGEL_ONE_SMARTAPI")),
            SealedBrokerEvidence.seal(
                _bundle("MT5", mode=BrokerExecutionMode.DEMO)
            ),
        )
    )
    assert not demo.phase11_eligible
    assert any("controlled-live" in reason for reason in demo.reasons)


def test_complete_external_manifests_are_structurally_eligible_only() -> None:
    evidence = (
        SealedBrokerEvidence.seal(_bundle("ANGEL_ONE_SMARTAPI")),
        SealedBrokerEvidence.seal(_bundle("MT5")),
    )
    default_assessment = BrokerEvidenceVerifier().assess(evidence)
    assert not default_assessment.phase11_eligible
    assert any("authorized external" in reason for reason in default_assessment.reasons)

    assessment = BrokerEvidenceVerifier(
        attestation_verifier=lambda _bundle: True
    ).assess(
        (
            SealedBrokerEvidence.seal(_bundle("ANGEL_ONE_SMARTAPI")),
            SealedBrokerEvidence.seal(_bundle("MT5")),
        )
    )
    assert assessment.phase11_eligible
    assert assessment.gate_decision == "PASS"
    assert assessment.execution_authority is False


def test_loader_rejects_secret_fields_before_schema_validation(tmp_path) -> None:
    sealed = SealedBrokerEvidence.seal(_bundle("MT5"))
    payload = sealed.model_dump(mode="json")
    payload["api_key"] = "must-not-be-here"
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden secret field"):
        load_sealed_broker_evidence(path)


def test_execution_evidence_rejects_overfill_and_noncausal_time() -> None:
    values = _execution().model_dump()
    values["filled_quantity"] = Decimal(2)
    with pytest.raises(ValidationError, match="overfill"):
        BrokerExecutionObservation(**values)

    values = _execution().model_dump()
    values["acknowledged_at"] = _START - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="not causal"):
        BrokerExecutionObservation(**values)


def test_verifier_rejects_cross_bundle_duplicate_observations() -> None:
    evidence = (
        SealedBrokerEvidence.seal(_bundle("MT5")),
        SealedBrokerEvidence.seal(_bundle("MT5", capture_suffix=":second")),
    )

    with pytest.raises(ValueError, match="duplicate execution probe_id"):
        BrokerEvidenceVerifier(attestation_verifier=lambda _bundle: True).assess(
            evidence
        )
