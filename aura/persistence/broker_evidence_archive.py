from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from aura.execution.broker_evidence import SealedBrokerEvidence
from aura.persistence.wal import JsonlWriteAheadLog, WalEvent

_EVENT_TYPE = "broker.evidence.sealed.v1"


class BrokerEvidenceArchiveError(RuntimeError):
    pass


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
