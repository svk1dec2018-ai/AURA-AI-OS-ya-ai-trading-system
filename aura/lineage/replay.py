from __future__ import annotations

from dataclasses import dataclass

from aura.lineage.decision import DecisionLineageRecord
from aura.persistence.wal import WalEvent


class DecisionLineageMismatch(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class DecisionLineageReplayVerifier:
    expected_event_type: str = "agent.round.completed"

    def verify_event(
        self,
        event: WalEvent,
        regenerated: DecisionLineageRecord,
    ) -> DecisionLineageRecord:
        if event.event_type != self.expected_event_type:
            raise DecisionLineageMismatch(
                f"unexpected audit event type: {event.event_type}"
            )
        raw_lineage = event.payload.get("lineage")
        if raw_lineage is None:
            raise DecisionLineageMismatch("audit event is missing decision lineage")
        try:
            stored = DecisionLineageRecord.model_validate(raw_lineage)
        except Exception as exc:
            raise DecisionLineageMismatch("audit event contains invalid lineage payload") from exc
        if not stored.verify_hash():
            raise DecisionLineageMismatch("stored decision lineage aggregate hash is invalid")
        if event.correlation_id != stored.correlation_id:
            raise DecisionLineageMismatch(
                "WAL correlation_id does not match stored decision lineage"
            )
        if regenerated.correlation_id != stored.correlation_id:
            raise DecisionLineageMismatch(
                "regenerated decision correlation_id does not match stored lineage"
            )
        if not regenerated.verify_hash():
            raise DecisionLineageMismatch("regenerated decision lineage hash is invalid")
        if regenerated.lineage_hash != stored.lineage_hash:
            raise DecisionLineageMismatch(
                "replay decision lineage mismatch: inputs or decision stages changed"
            )
        return stored
