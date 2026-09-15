from __future__ import annotations

from aura.evolution.online_learning import (
    OnlineEventKind,
    OnlineLearningEvent,
    OutcomeLabel,
    ResearchTrigger,
    SafeOnlineLearner,
)
from aura.evolution.opportunity_audit import OpportunityAuditRecord, OpportunityOutcome

_OUTCOME_MAP = {
    OpportunityOutcome.CAPTURED: OutcomeLabel.CAPTURED,
    OpportunityOutcome.MISSED_FLAT: OutcomeLabel.MISSED,
    OpportunityOutcome.WRONG_DIRECTION: OutcomeLabel.WRONG_DIRECTION,
    OpportunityOutcome.BLOCKED_SAFETY: OutcomeLabel.SAFE_BLOCK,
    OpportunityOutcome.NO_MATERIAL_MOVE: OutcomeLabel.NEUTRAL,
}


class OpportunityOnlineLearningBridge:
    """Feed ex-post live opportunity labels into O(1) online measurements."""

    def __init__(
        self,
        learner: SafeOnlineLearner,
        *,
        market: str,
        regime: str = "UNKNOWN",
    ) -> None:
        if not market.strip():
            raise ValueError("online-learning market cannot be empty")
        self.learner = learner
        self.market = market.strip().upper()
        self.regime = regime.strip().upper() or "UNKNOWN"
        self.triggers: list[ResearchTrigger] = []
        self._observed_record_ids: set[str] = set()
        self.replayed_records = 0

    def observe_records(
        self,
        records: tuple[OpportunityAuditRecord, ...] | list[OpportunityAuditRecord],
    ) -> tuple[ResearchTrigger, ...]:
        emitted: list[ResearchTrigger] = []
        ordered = sorted(records, key=lambda item: (item.resolved_time, item.record_id))
        for record in ordered:
            if record.record_id in self._observed_record_ids:
                continue
            realized_correct: bool | None = None
            if record.outcome == OpportunityOutcome.CAPTURED:
                realized_correct = True
            elif record.outcome == OpportunityOutcome.WRONG_DIRECTION:
                realized_correct = False
            trigger = self.learner.observe(
                OnlineLearningEvent(
                    kind=OnlineEventKind.OUTCOME,
                    market=self.market,
                    symbol=record.symbol,
                    regime=self.regime,
                    observed_at=record.resolved_time,
                    confidence=(
                        record.memo_confidence
                        if realized_correct is not None
                        else None
                    ),
                    realized_correct=realized_correct,
                    outcome=_OUTCOME_MAP[record.outcome],
                )
            )
            self._observed_record_ids.add(record.record_id)
            if trigger.due:
                emitted.append(trigger)
                self.triggers.append(trigger)
        return tuple(emitted)

    def replay_records(
        self,
        records: tuple[OpportunityAuditRecord, ...] | list[OpportunityAuditRecord],
    ) -> tuple[ResearchTrigger, ...]:
        """Deterministically rebuild online measurements from the durable audit."""

        before = len(self._observed_record_ids)
        triggers = self.observe_records(records)
        self.replayed_records += len(self._observed_record_ids) - before
        return triggers

    def status(self) -> dict:
        snapshots = self.learner.snapshots()
        return {
            "tracked_states": len(snapshots),
            "observed_records": len(self._observed_record_ids),
            "replayed_records": self.replayed_records,
            "research_triggers": len(self.triggers),
            "latest_trigger": (
                self.triggers[-1].model_dump(mode="json") if self.triggers else None
            ),
            "states": [item.model_dump(mode="json") for item in snapshots[-50:]],
        }
