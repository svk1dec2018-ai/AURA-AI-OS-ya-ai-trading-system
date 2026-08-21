from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

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
from aura.ops.broker_evidence_custody import (
    BrokerEvidenceCustodyError,
    custody_broker_evidence_files,
    main,
)
from aura.persistence.broker_evidence_archive import BrokerEvidenceArchive

_START = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


def _evidence(adapter: str) -> SealedBrokerEvidence:
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
    reconciliations = tuple(
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
    return SealedBrokerEvidence.seal(
        BrokerEvidenceBundle(
            capture_id=f"{adapter}:capture",
            adapter_name=adapter,
            mode=BrokerExecutionMode.CONTROLLED_LIVE,
            source=BrokerEvidenceSource.AUTHORIZED_EXTERNAL_BROKER,
            environment_verified=True,
            account_fingerprint="d" * 64,
            attestation_fingerprint="e" * 64,
            captured_at=_START + timedelta(minutes=1),
            executions=(execution,),
            reconciliation_runs=reconciliations,
        )
    )


def _write_inputs(
    root: Path,
    *,
    review_quorum: bool = True,
) -> tuple[tuple[Path, ...], Path, tuple[SealedBrokerEvidence, ...]]:
    evidence = tuple(
        _evidence(adapter) for adapter in ("ANGEL_ONE_SMARTAPI", "MT5")
    )
    paths = tuple(root / f"evidence-{index}.json" for index in range(2))
    for path, item in zip(paths, evidence, strict=True):
        path.write_text(item.model_dump_json(), encoding="utf-8")
    reviews = (
        tuple(
            BrokerAttestationReview(
                bundle_sha256=item.sha256,
                reviewer_fingerprint=reviewer * 64,
                reviewed_at=_START + timedelta(minutes=2 + index),
            )
            for item in evidence
            for index, reviewer in enumerate(("1", "2"))
        )
        if review_quorum
        else ()
    )
    registry = SealedBrokerAttestationRegistry.seal(
        BrokerAttestationRegistry(
            registry_id="owner-reviewed-custody-batch",
            generated_at=_START + timedelta(minutes=10),
            reviews=reviews,
        )
    )
    registry_path = root / "registry.json"
    registry_path.write_text(registry.model_dump_json(), encoding="utf-8")
    return paths, registry_path, evidence


def _custody_paths(root: Path) -> tuple[Path, Path, Path]:
    return (
        root / "runtime" / "evidence.wal",
        root / "external" / "checkpoint.json",
        root / "external" / "receipt.json",
    )


def test_eligible_batch_is_archived_anchored_and_receipted(tmp_path: Path) -> None:
    paths, registry_path, evidence = _write_inputs(tmp_path)
    archive_path, checkpoint_path, receipt_path = _custody_paths(tmp_path)

    sealed = custody_broker_evidence_files(
        paths,
        attestation_registry_path=registry_path,
        archive_path=archive_path,
        checkpoint_path=checkpoint_path,
        receipt_path=receipt_path,
    )

    archive = BrokerEvidenceArchive(archive_path, fsync=False)
    checkpoint = archive.load_checkpoint(checkpoint_path)
    archive.verify_checkpoint(checkpoint)
    assert {item.evidence.sha256 for item in archive.read_all()} == {
        item.sha256 for item in evidence
    }
    assert sealed.receipt.archive_checkpoint_sha256 == checkpoint.sha256
    assert sealed.receipt.archive_checkpoint_record_count == 2
    assert sealed.receipt.phase_gate_updated is False
    assert sealed.receipt.phase11_pass_claimed is False
    assert sealed.receipt.execution_authority is False
    assert receipt_path.stat().st_mode & 0o777 == 0o600


def test_blocked_batch_performs_no_custody_writes(tmp_path: Path) -> None:
    paths, registry_path, _ = _write_inputs(tmp_path, review_quorum=False)
    archive_path, checkpoint_path, receipt_path = _custody_paths(tmp_path)

    with pytest.raises(BrokerEvidenceCustodyError, match="not eligible"):
        custody_broker_evidence_files(
            paths,
            attestation_registry_path=registry_path,
            archive_path=archive_path,
            checkpoint_path=checkpoint_path,
            receipt_path=receipt_path,
        )

    assert not archive_path.exists()
    assert not checkpoint_path.exists()
    assert not receipt_path.exists()


def test_custody_restart_is_idempotent(tmp_path: Path) -> None:
    paths, registry_path, _ = _write_inputs(tmp_path)
    archive_path, checkpoint_path, receipt_path = _custody_paths(tmp_path)
    kwargs = {
        "attestation_registry_path": registry_path,
        "archive_path": archive_path,
        "checkpoint_path": checkpoint_path,
        "receipt_path": receipt_path,
    }

    first = custody_broker_evidence_files(paths, **kwargs)
    second = custody_broker_evidence_files(tuple(reversed(paths)), **kwargs)

    assert second == first
    assert len(archive_path.read_text(encoding="utf-8").splitlines()) == 2


def test_custody_resumes_after_partial_archive_append(tmp_path: Path) -> None:
    paths, registry_path, evidence = _write_inputs(tmp_path)
    archive_path, checkpoint_path, receipt_path = _custody_paths(tmp_path)
    BrokerEvidenceArchive(archive_path, fsync=False).append(evidence[0])

    sealed = custody_broker_evidence_files(
        paths,
        attestation_registry_path=registry_path,
        archive_path=archive_path,
        checkpoint_path=checkpoint_path,
        receipt_path=receipt_path,
    )

    assert len(BrokerEvidenceArchive(archive_path, fsync=False).read_all()) == 2
    assert sealed.receipt.archive_checkpoint_record_count == 2
    assert checkpoint_path.exists()
    assert receipt_path.exists()


def test_existing_checkpoint_rejects_new_evidence_before_append(tmp_path: Path) -> None:
    paths, registry_path, evidence = _write_inputs(tmp_path)
    archive_path, checkpoint_path, receipt_path = _custody_paths(tmp_path)
    archive = BrokerEvidenceArchive(archive_path, fsync=False)
    archive.append(evidence[0])
    archive.export_checkpoint(checkpoint_path)

    with pytest.raises(BrokerEvidenceCustodyError, match="use a new path"):
        custody_broker_evidence_files(
            paths,
            attestation_registry_path=registry_path,
            archive_path=archive_path,
            checkpoint_path=checkpoint_path,
            receipt_path=receipt_path,
        )

    assert len(BrokerEvidenceArchive(archive_path, fsync=False).read_all()) == 1
    assert not receipt_path.exists()


def test_existing_checkpoint_rejects_unanchored_existing_record(tmp_path: Path) -> None:
    paths, registry_path, evidence = _write_inputs(tmp_path)
    archive_path, checkpoint_path, receipt_path = _custody_paths(tmp_path)
    archive = BrokerEvidenceArchive(archive_path, fsync=False)
    archive.append(evidence[0])
    archive.export_checkpoint(checkpoint_path)
    archive.append(evidence[1])

    with pytest.raises(BrokerEvidenceCustodyError, match="does not cover"):
        custody_broker_evidence_files(
            paths,
            attestation_registry_path=registry_path,
            archive_path=archive_path,
            checkpoint_path=checkpoint_path,
            receipt_path=receipt_path,
        )

    assert not receipt_path.exists()


def test_custody_rejects_overlapping_paths_before_mutation(tmp_path: Path) -> None:
    paths, registry_path, _ = _write_inputs(tmp_path)
    _, checkpoint_path, receipt_path = _custody_paths(tmp_path)

    with pytest.raises(BrokerEvidenceCustodyError, match="paths must be distinct"):
        custody_broker_evidence_files(
            paths,
            attestation_registry_path=registry_path,
            archive_path=paths[0],
            checkpoint_path=checkpoint_path,
            receipt_path=receipt_path,
        )


def test_tampered_existing_receipt_fails_closed(tmp_path: Path) -> None:
    paths, registry_path, _ = _write_inputs(tmp_path)
    archive_path, checkpoint_path, receipt_path = _custody_paths(tmp_path)
    kwargs = {
        "attestation_registry_path": registry_path,
        "archive_path": archive_path,
        "checkpoint_path": checkpoint_path,
        "receipt_path": receipt_path,
    }
    custody_broker_evidence_files(paths, **kwargs)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["receipt"]["phase_gate_updated"] = True
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BrokerEvidenceCustodyError, match="invalid existing"):
        custody_broker_evidence_files(paths, **kwargs)


def test_custody_cli_reports_review_only_status(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    paths, registry_path, _ = _write_inputs(tmp_path)
    archive_path, checkpoint_path, receipt_path = _custody_paths(tmp_path)
    argv = ["broker-evidence-custody"]
    for path in paths:
        argv.extend(("--evidence", str(path)))
    argv.extend(
        (
            "--attestation-registry",
            str(registry_path),
            "--archive",
            str(archive_path),
            "--checkpoint",
            str(checkpoint_path),
            "--receipt",
            str(receipt_path),
        )
    )
    monkeypatch.setattr("sys.argv", argv)

    assert main() == 0
    output = capsys.readouterr().out
    assert "Phase 11 remains review-only" in output
    assert "execution authority remains disabled" in output
