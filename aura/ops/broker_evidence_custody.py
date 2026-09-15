from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aura.execution.broker_evidence import (
    BrokerEvidenceVerifier,
    SealedBrokerEvidence,
    load_sealed_broker_attestation_registry,
    load_sealed_broker_evidence,
)
from aura.persistence.broker_evidence_archive import (
    BrokerEvidenceArchive,
    BrokerEvidenceArchiveError,
    SealedBrokerEvidenceArchiveCheckpoint,
)


class BrokerEvidenceCustodyError(RuntimeError):
    pass


class CustodiedEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_sequence: int = Field(ge=1)


class BrokerEvidenceCustodyReceipt(BaseModel):
    """Non-authoritative receipt for one validated offline custody batch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    phase: Literal[11] = 11
    custody_decision: Literal["ELIGIBLE_FOR_GATE_REVIEW_ARCHIVED"] = (
        "ELIGIBLE_FOR_GATE_REVIEW_ARCHIVED"
    )
    evidence: tuple[CustodiedEvidenceRecord, ...]
    attestation_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_checkpoint_record_count: int = Field(ge=1)
    phase_gate_updated: Literal[False] = False
    phase11_pass_claimed: Literal[False] = False
    execution_authority: Literal[False] = False
    broker_connection_performed: Literal[False] = False

    @model_validator(mode="after")
    def evidence_must_be_unique_and_ordered(self) -> BrokerEvidenceCustodyReceipt:
        hashes = tuple(item.evidence_sha256 for item in self.evidence)
        if not hashes or hashes != tuple(sorted(set(hashes))):
            raise ValueError("custody receipt evidence must be unique and hash ordered")
        if any(
            item.archive_sequence > self.archive_checkpoint_record_count
            for item in self.evidence
        ):
            raise ValueError("custody receipt evidence is outside checkpoint prefix")
        return self


class SealedBrokerEvidenceCustodyReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt: BrokerEvidenceCustodyReceipt
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> SealedBrokerEvidenceCustodyReceipt:
        expected = _sha256(self.receipt.model_dump(mode="json"))
        if self.sha256 != expected:
            raise ValueError("broker evidence custody receipt hash mismatch")
        return self

    @classmethod
    def seal(
        cls,
        receipt: BrokerEvidenceCustodyReceipt,
    ) -> SealedBrokerEvidenceCustodyReceipt:
        return cls(receipt=receipt, sha256=_sha256(receipt.model_dump(mode="json")))


def custody_broker_evidence_files(
    evidence_paths: tuple[Path, ...],
    *,
    attestation_registry_path: Path,
    archive_path: Path,
    checkpoint_path: Path,
    receipt_path: Path,
) -> SealedBrokerEvidenceCustodyReceipt:
    """Validate, archive and anchor an eligible batch without broker authority."""

    normalized_paths = tuple(path.resolve() for path in evidence_paths)
    if not normalized_paths:
        raise BrokerEvidenceCustodyError("custody batch requires broker evidence")
    if len(set(normalized_paths)) != len(normalized_paths):
        raise BrokerEvidenceCustodyError("duplicate broker evidence input path")
    source_paths = set(normalized_paths) | {attestation_registry_path.resolve()}
    custody_paths = {
        archive_path.resolve(),
        checkpoint_path.resolve(),
        receipt_path.resolve(),
    }
    if len(custody_paths) != 3 or source_paths & custody_paths:
        raise BrokerEvidenceCustodyError("custody input and output paths must be distinct")

    evidence = tuple(
        sorted(
            (load_sealed_broker_evidence(path) for path in normalized_paths),
            key=lambda item: item.sha256,
        )
    )
    if len({item.sha256 for item in evidence}) != len(evidence):
        raise BrokerEvidenceCustodyError("duplicate sealed broker evidence")
    registry = load_sealed_broker_attestation_registry(
        attestation_registry_path.resolve()
    )
    verifier = BrokerEvidenceVerifier(
        attestation_verifier=registry.registry.verifies
    )
    adapter_names = {item.bundle.adapter_name.strip().upper() for item in evidence}
    unsupported = adapter_names - set(verifier.policy.required_adapters)
    if unsupported:
        raise BrokerEvidenceCustodyError(
            "custody batch contains unsupported adapter: " + ", ".join(sorted(unsupported))
        )
    assessment = verifier.assess(evidence)
    if not assessment.phase11_eligible:
        raise BrokerEvidenceCustodyError(
            "broker evidence is not eligible for gate review: "
            + "; ".join(assessment.reasons)
        )

    archive = BrokerEvidenceArchive(archive_path)
    existing_checkpoint = _load_existing_checkpoint(archive, checkpoint_path)
    missing = tuple(item for item in evidence if archive.get(item.sha256) is None)
    if existing_checkpoint is not None and missing:
        raise BrokerEvidenceCustodyError(
            "existing checkpoint cannot anchor new custody evidence; use a new path"
        )
    if existing_checkpoint is not None and any(
        _required_sequence(archive, item)
        > existing_checkpoint.checkpoint.record_count
        for item in evidence
    ):
        raise BrokerEvidenceCustodyError(
            "existing checkpoint does not cover custody evidence; use a new path"
        )

    for item in evidence:
        archive.append(item)
    checkpoint = existing_checkpoint or archive.export_checkpoint(checkpoint_path)
    archive.verify_checkpoint(checkpoint)

    records = tuple(
        CustodiedEvidenceRecord(
            evidence_sha256=item.sha256,
            archive_sequence=_required_sequence(archive, item),
        )
        for item in evidence
    )
    sealed = SealedBrokerEvidenceCustodyReceipt.seal(
        BrokerEvidenceCustodyReceipt(
            evidence=records,
            attestation_registry_sha256=registry.sha256,
            archive_checkpoint_sha256=checkpoint.sha256,
            archive_checkpoint_record_count=checkpoint.checkpoint.record_count,
        )
    )
    _write_or_verify_receipt(receipt_path, sealed)
    return sealed


def _load_existing_checkpoint(
    archive: BrokerEvidenceArchive,
    path: Path,
) -> SealedBrokerEvidenceArchiveCheckpoint | None:
    if not path.exists():
        return None
    checkpoint = archive.load_checkpoint(path)
    archive.verify_checkpoint(checkpoint)
    return checkpoint


def _required_sequence(
    archive: BrokerEvidenceArchive,
    evidence: SealedBrokerEvidence,
) -> int:
    record = archive.get(evidence.sha256)
    if record is None:
        raise BrokerEvidenceCustodyError("custody archive lost appended evidence")
    return record.sequence


def _write_or_verify_receipt(
    path: Path,
    sealed: SealedBrokerEvidenceCustodyReceipt,
) -> None:
    if path.exists():
        try:
            existing = SealedBrokerEvidenceCustodyReceipt.model_validate_json(
                path.read_bytes()
            )
        except (OSError, ValueError) as exc:
            raise BrokerEvidenceCustodyError("invalid existing custody receipt") from exc
        if existing != sealed:
            raise BrokerEvidenceCustodyError("existing custody receipt does not match")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    encoded = (
        json.dumps(
            sealed.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise BrokerEvidenceCustodyError(
                f"custody receipt already exists: {path}"
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and archive eligible Phase 11 broker evidence offline"
    )
    parser.add_argument("--evidence", action="append", required=True, type=Path)
    parser.add_argument("--attestation-registry", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    try:
        sealed = custody_broker_evidence_files(
            tuple(args.evidence),
            attestation_registry_path=args.attestation_registry,
            archive_path=args.archive,
            checkpoint_path=args.checkpoint,
            receipt_path=args.receipt,
        )
    except (BrokerEvidenceCustodyError, BrokerEvidenceArchiveError, OSError, ValueError) as exc:
        print(f"Broker evidence custody failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Broker evidence custody archived: {sealed.sha256}; "
        "Phase 11 remains review-only and execution authority remains disabled"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
