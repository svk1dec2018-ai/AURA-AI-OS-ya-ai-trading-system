from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aura.execution.broker_evidence import SealedBrokerEvidence
from aura.persistence.wal import JsonlWriteAheadLog, WalEvent

_EVENT_TYPE = "broker.evidence.sealed.v1"


class BrokerEvidenceArchiveError(RuntimeError):
    pass


class BrokerEvidenceArchiveCheckpoint(BaseModel):
    """Credential-free description of one externally anchorable archive prefix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    record_count: int = Field(ge=1)
    last_sequence: int = Field(ge=1)
    last_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    wal_prefix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def sequence_must_match_record_count(self) -> BrokerEvidenceArchiveCheckpoint:
        if self.last_sequence != self.record_count:
            raise ValueError("archive checkpoint sequence does not match record count")
        return self


class SealedBrokerEvidenceArchiveCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint: BrokerEvidenceArchiveCheckpoint
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> SealedBrokerEvidenceArchiveCheckpoint:
        expected = _checkpoint_sha256(self.checkpoint)
        if self.sha256 != expected:
            raise ValueError("broker evidence archive checkpoint hash mismatch")
        return self

    @classmethod
    def seal(
        cls,
        checkpoint: BrokerEvidenceArchiveCheckpoint,
    ) -> SealedBrokerEvidenceArchiveCheckpoint:
        return cls(checkpoint=checkpoint, sha256=_checkpoint_sha256(checkpoint))


@dataclass(frozen=True, slots=True)
class ArchivedBrokerEvidence:
    sequence: int
    evidence: SealedBrokerEvidence


@dataclass(frozen=True, slots=True)
class BrokerEvidenceAppendResult:
    record: ArchivedBrokerEvidence
    appended: bool


class BrokerEvidenceArchive:
    """Restart-safe append-only chain of custody for already-sealed evidence.

    The archive reuses AURA's checksum/sequence protected WAL. It performs no
    broker I/O and exposes no deletion or mutation operation.
    """

    def __init__(self, path: str | Path, *, fsync: bool = True) -> None:
        self._lock = RLock()
        self._wal = JsonlWriteAheadLog(path, fsync=fsync)
        self._records = self._recover()

    @property
    def path(self) -> Path:
        return self._wal.path

    def append(self, evidence: SealedBrokerEvidence) -> BrokerEvidenceAppendResult:
        with self._lock:
            existing = self._records.get(evidence.sha256)
            if existing is not None:
                return BrokerEvidenceAppendResult(record=existing, appended=False)

            previous_sha256 = next(reversed(self._records), None)
            event = self._wal.append(
                event_type=_EVENT_TYPE,
                payload={
                    "evidence": evidence.model_dump(mode="json"),
                    "previous_evidence_sha256": previous_sha256,
                },
                correlation_id=evidence.bundle.capture_id,
                event_id=evidence.sha256,
            )
            record = self._decode_event(
                event,
                expected_previous_sha256=previous_sha256,
            )
            self._records[evidence.sha256] = record
            return BrokerEvidenceAppendResult(record=record, appended=True)

    def read_all(self) -> tuple[ArchivedBrokerEvidence, ...]:
        with self._lock:
            records = self._recover()
            self._records = records
            return tuple(records[key] for key in records)

    def get(self, evidence_sha256: str) -> ArchivedBrokerEvidence | None:
        with self._lock:
            return self._records.get(evidence_sha256)

    def checkpoint(self) -> SealedBrokerEvidenceArchiveCheckpoint:
        """Seal the current WAL prefix for storage in an owner-controlled system."""

        with self._lock:
            records = self._recover()
            if not records:
                raise BrokerEvidenceArchiveError("cannot checkpoint an empty archive")
            self._records = records
            last = next(reversed(records.values()))
            prefix = self._wal_prefix_bytes(len(records))
            return SealedBrokerEvidenceArchiveCheckpoint.seal(
                BrokerEvidenceArchiveCheckpoint(
                    record_count=len(records),
                    last_sequence=last.sequence,
                    last_evidence_sha256=last.evidence.sha256,
                    wal_prefix_sha256=hashlib.sha256(prefix).hexdigest(),
                )
            )

    def export_checkpoint(self, path: str | Path) -> SealedBrokerEvidenceArchiveCheckpoint:
        """Create, fsync and exclusively persist a sealed external-anchor file."""

        checkpoint = self.checkpoint()
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        encoded = (
            json.dumps(
                checkpoint.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError as exc:
                raise BrokerEvidenceArchiveError(
                    f"archive checkpoint already exists: {destination}"
                ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return checkpoint

    @staticmethod
    def load_checkpoint(path: str | Path) -> SealedBrokerEvidenceArchiveCheckpoint:
        try:
            return SealedBrokerEvidenceArchiveCheckpoint.model_validate_json(
                Path(path).read_bytes()
            )
        except (OSError, ValueError) as exc:
            raise BrokerEvidenceArchiveError("invalid broker evidence checkpoint") from exc

    def verify_checkpoint(
        self,
        sealed: SealedBrokerEvidenceArchiveCheckpoint,
    ) -> None:
        """Fail closed unless the sealed archive prefix remains intact."""

        with self._lock:
            records = self._recover()
            checkpoint = sealed.checkpoint
            if len(records) < checkpoint.record_count:
                raise BrokerEvidenceArchiveError(
                    "broker evidence archive is shorter than checkpoint"
                )
            anchored = tuple(records.values())[checkpoint.record_count - 1]
            if anchored.sequence != checkpoint.last_sequence:
                raise BrokerEvidenceArchiveError(
                    "broker evidence checkpoint sequence mismatch"
                )
            if anchored.evidence.sha256 != checkpoint.last_evidence_sha256:
                raise BrokerEvidenceArchiveError(
                    "broker evidence checkpoint tail mismatch"
                )
            prefix_sha256 = hashlib.sha256(
                self._wal_prefix_bytes(checkpoint.record_count)
            ).hexdigest()
            if prefix_sha256 != checkpoint.wal_prefix_sha256:
                raise BrokerEvidenceArchiveError(
                    "broker evidence checkpoint WAL prefix mismatch"
                )

    def _wal_prefix_bytes(self, record_count: int) -> bytes:
        raw = self.path.read_bytes() if self.path.exists() else b""
        prefix: list[bytes] = []
        records_seen = 0
        for line in raw.splitlines(keepends=True):
            prefix.append(line)
            if line.strip():
                records_seen += 1
            if records_seen == record_count:
                return b"".join(prefix)
        raise BrokerEvidenceArchiveError("archive WAL prefix is incomplete")

    def _recover(self) -> dict[str, ArchivedBrokerEvidence]:
        records: dict[str, ArchivedBrokerEvidence] = {}
        previous_sha256: str | None = None
        for event in self._wal.read_all():
            record = self._decode_event(
                event,
                expected_previous_sha256=previous_sha256,
            )
            digest = record.evidence.sha256
            if digest in records:
                raise BrokerEvidenceArchiveError(
                    f"duplicate sealed evidence in archive: {digest}"
                )
            records[digest] = record
            previous_sha256 = digest
        return records

    @staticmethod
    def _decode_event(
        event: WalEvent,
        *,
        expected_previous_sha256: str | None,
    ) -> ArchivedBrokerEvidence:
        if event.event_type != _EVENT_TYPE:
            raise BrokerEvidenceArchiveError(
                f"unsupported broker evidence archive event: {event.event_type}"
            )
        if set(event.payload) != {"evidence", "previous_evidence_sha256"}:
            raise BrokerEvidenceArchiveError("invalid broker evidence archive payload")
        if event.payload["previous_evidence_sha256"] != expected_previous_sha256:
            raise BrokerEvidenceArchiveError("broker evidence archive hash-chain mismatch")
        try:
            evidence = SealedBrokerEvidence.model_validate(event.payload["evidence"])
        except (TypeError, ValueError) as exc:
            raise BrokerEvidenceArchiveError(
                "sealed broker evidence payload validation failed"
            ) from exc
        if event.event_id != evidence.sha256:
            raise BrokerEvidenceArchiveError(
                "archive event ID does not match sealed evidence hash"
            )
        if event.correlation_id != evidence.bundle.capture_id:
            raise BrokerEvidenceArchiveError(
                "archive correlation ID does not match evidence capture ID"
            )
        return ArchivedBrokerEvidence(sequence=event.sequence, evidence=evidence)


def _checkpoint_sha256(checkpoint: BrokerEvidenceArchiveCheckpoint) -> str:
    canonical = json.dumps(
        checkpoint.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
