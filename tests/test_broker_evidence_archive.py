from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aura.execution.broker import BrokerExecutionMode
from aura.execution.broker_evidence import (
    BrokerEvidenceBundle,
    BrokerEvidenceSource,
    SealedBrokerEvidence,
)
from aura.persistence.broker_evidence_archive import (
    BrokerEvidenceArchive,
    BrokerEvidenceArchiveError,
)
from aura.persistence.wal import CorruptWalError, JsonlWriteAheadLog

_CAPTURED_AT = datetime(2026, 8, 21, 6, 0, tzinfo=UTC)


def _evidence(capture_id: str = "capture:test") -> SealedBrokerEvidence:
    return SealedBrokerEvidence.seal(
        BrokerEvidenceBundle(
            capture_id=capture_id,
            adapter_name="MT5",
            mode=BrokerExecutionMode.DEMO,
            source=BrokerEvidenceSource.INTERNAL_FIXTURE,
            environment_verified=True,
            account_fingerprint="a" * 64,
            attestation_fingerprint="b" * 64,
            captured_at=_CAPTURED_AT,
            executions=(),
            reconciliation_runs=(),
        )
    )


def test_archive_is_restart_safe_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "broker-evidence.wal"
    evidence = _evidence()
    archive = BrokerEvidenceArchive(path, fsync=False)

    first = archive.append(evidence)
    duplicate = archive.append(evidence)
    reopened = BrokerEvidenceArchive(path, fsync=False)

    assert first.appended is True
    assert duplicate.appended is False
    assert duplicate.record.sequence == first.record.sequence == 1
    assert reopened.get(evidence.sha256) == first.record
    assert reopened.read_all() == (first.record,)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_archive_links_sequential_evidence_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "broker-evidence.wal"
    first_evidence = _evidence("capture:first")
    second_evidence = _evidence("capture:second")
    archive = BrokerEvidenceArchive(path, fsync=False)

    first = archive.append(first_evidence).record
    second = archive.append(second_evidence).record
    raw_records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]

    assert raw_records[0]["event"]["payload"]["previous_evidence_sha256"] is None
    assert (
        raw_records[1]["event"]["payload"]["previous_evidence_sha256"]
        == first_evidence.sha256
    )
    assert BrokerEvidenceArchive(path, fsync=False).read_all() == (first, second)


def test_concurrent_duplicate_append_writes_one_record(tmp_path: Path) -> None:
    archive = BrokerEvidenceArchive(tmp_path / "broker-evidence.wal", fsync=False)
    evidence = _evidence()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(archive.append, [evidence] * 20))

    assert sum(result.appended for result in results) == 1
    assert len(archive.read_all()) == 1


def test_archive_detects_wal_checksum_tampering(tmp_path: Path) -> None:
    path = tmp_path / "broker-evidence.wal"
    archive = BrokerEvidenceArchive(path, fsync=False)
    archive.append(_evidence())
    record = json.loads(path.read_text(encoding="utf-8"))
    record["event"]["correlation_id"] = "tampered"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(CorruptWalError, match="checksum mismatch"):
        BrokerEvidenceArchive(path, fsync=False)


def test_archive_rejects_semantically_invalid_wal_events(tmp_path: Path) -> None:
    path = tmp_path / "broker-evidence.wal"
    wal = JsonlWriteAheadLog(path, fsync=False)
    wal.append(
        event_type="unrelated.event",
        payload={
            "evidence": _evidence().model_dump(mode="json"),
            "previous_evidence_sha256": None,
        },
        correlation_id="capture:test",
        event_id=_evidence().sha256,
    )

    with pytest.raises(BrokerEvidenceArchiveError, match="unsupported"):
        BrokerEvidenceArchive(path, fsync=False)


def test_archive_rejects_valid_checksum_with_wrong_chain_binding(tmp_path: Path) -> None:
    path = tmp_path / "broker-evidence.wal"
    evidence = _evidence()
    wal = JsonlWriteAheadLog(path, fsync=False)
    wal.append(
        event_type="broker.evidence.sealed.v1",
        payload={
            "evidence": evidence.model_dump(mode="json"),
            "previous_evidence_sha256": None,
        },
        correlation_id="wrong-capture-id",
        event_id=evidence.sha256,
    )

    with pytest.raises(BrokerEvidenceArchiveError, match="correlation ID"):
        BrokerEvidenceArchive(path, fsync=False)


def test_archive_rejects_valid_checksum_with_wrong_hash_chain(tmp_path: Path) -> None:
    path = tmp_path / "broker-evidence.wal"
    evidence = _evidence()
    wal = JsonlWriteAheadLog(path, fsync=False)
    wal.append(
        event_type="broker.evidence.sealed.v1",
        payload={
            "evidence": evidence.model_dump(mode="json"),
            "previous_evidence_sha256": "f" * 64,
        },
        correlation_id=evidence.bundle.capture_id,
        event_id=evidence.sha256,
    )

    with pytest.raises(BrokerEvidenceArchiveError, match="hash-chain mismatch"):
        BrokerEvidenceArchive(path, fsync=False)
