from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aura.execution.broker import BrokerExecutionMode
from aura.execution.broker_evidence import (
    BrokerEvidenceBundle,
    BrokerEvidenceSource,
    SealedBrokerEvidence,
)
from aura.ops.broker_evidence_checkpoint import main
from aura.persistence.broker_evidence_archive import BrokerEvidenceArchive


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
            captured_at=datetime(2026, 8, 21, 6, 0, tzinfo=UTC),
            executions=(),
            reconciliation_runs=(),
        )
    )


def test_checkpoint_cli_exports_and_verifies(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    archive_path = tmp_path / "broker-evidence.wal"
    checkpoint_path = tmp_path / "external" / "anchor.json"
    archive = BrokerEvidenceArchive(archive_path, fsync=False)
    archive.append(_evidence())

    monkeypatch.setattr(
        "sys.argv",
        [
            "broker-evidence-checkpoint",
            "export",
            "--archive",
            str(archive_path),
            "--checkpoint",
            str(checkpoint_path),
        ],
    )
    assert main() == 0
    assert "execution authority remains disabled" in capsys.readouterr().out

    monkeypatch.setattr(
        "sys.argv",
        [
            "broker-evidence-checkpoint",
            "verify",
            "--archive",
            str(archive_path),
            "--checkpoint",
            str(checkpoint_path),
        ],
    )
    assert main() == 0
    assert "checkpoint verified" in capsys.readouterr().out


def test_checkpoint_cli_fails_closed_after_archive_rollback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    archive_path = tmp_path / "broker-evidence.wal"
    checkpoint_path = tmp_path / "external" / "anchor.json"
    archive = BrokerEvidenceArchive(archive_path, fsync=False)
    archive.append(_evidence("capture:first"))
    archive.append(_evidence("capture:second"))
    archive.export_checkpoint(checkpoint_path)
    archive_path.write_bytes(archive_path.read_bytes().splitlines(keepends=True)[0])

    monkeypatch.setattr(
        "sys.argv",
        [
            "broker-evidence-checkpoint",
            "verify",
            "--archive",
            str(archive_path),
            "--checkpoint",
            str(checkpoint_path),
        ],
    )
    assert main() == 2
    assert "shorter than checkpoint" in capsys.readouterr().err


def test_checkpoint_cli_rejects_tampered_anchor(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    archive_path = tmp_path / "broker-evidence.wal"
    checkpoint_path = tmp_path / "anchor.json"
    archive = BrokerEvidenceArchive(archive_path, fsync=False)
    archive.append(_evidence())
    archive.export_checkpoint(checkpoint_path)
    checkpoint_path.write_text(
        checkpoint_path.read_text(encoding="utf-8").replace('"record_count":1', '"record_count":2'),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "broker-evidence-checkpoint",
            "verify",
            "--archive",
            str(archive_path),
            "--checkpoint",
            str(checkpoint_path),
        ],
    )
    assert main() == 2
    assert "invalid broker evidence checkpoint" in capsys.readouterr().err
