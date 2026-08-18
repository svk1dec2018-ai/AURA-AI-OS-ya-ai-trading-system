from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.domain.models import NormalizedCandle, SignalIntent
from aura.runtime.scanner import MarketScanResult, ScanCandidate


class OpportunityOutcome(str, Enum):
    NO_MATERIAL_MOVE = "no_material_move"
    CAPTURED = "captured"
    MISSED_FLAT = "missed_flat"
    WRONG_DIRECTION = "wrong_direction"
    BLOCKED_SAFETY = "blocked_safety"


class OpportunityAuditPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon_bars: int = Field(default=5, ge=1)
    atr_period: int = Field(default=14, ge=5)
    min_move_atr_multiple: float = Field(default=1.0, gt=0)


class OpportunityAuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str = Field(min_length=1)
    decision_time: datetime
    resolved_time: datetime
    symbol: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    raw_intent: SignalIntent
    realized_direction: SignalIntent
    move_atr_multiple: float
    outcome: OpportunityOutcome
    memo_confidence: float = Field(ge=0, le=1)

    @field_validator("decision_time", "resolved_time")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("opportunity audit timestamps must be timezone-aware")
        return value


@dataclass(slots=True)
class _PendingOpportunity:
    record_id: str
    decision_time: datetime
    symbol: str
    timeframe: str
    entry_price: Decimal
    atr: Decimal
    raw_intent: SignalIntent
    memo_confidence: float
    safety_allowed: bool
    bars_seen: int = 0


@dataclass(slots=True, frozen=True)
class OpportunityAuditMetrics:
    material_opportunities: int
    captured: int
    missed_flat: int
    wrong_direction: int
    blocked_safety: int

    @property
    def capture_rate(self) -> float:
        if self.material_opportunities <= 0:
            return 0.0
        return self.captured / self.material_opportunities


class OpportunityAuditStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._known_ids = {record.record_id for record in self.read_all()}

    def append(self, record: OpportunityAuditRecord) -> bool:
        if record.record_id in self._known_ids:
            return False
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._known_ids.add(record.record_id)
        return True

    def read_all(self) -> tuple[OpportunityAuditRecord, ...]:
        if not self.path.exists():
            return ()
        records: list[OpportunityAuditRecord] = []
        seen: set[str] = set()
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                record = OpportunityAuditRecord.model_validate_json(line)
            except Exception as exc:
                raise RuntimeError(
                    f"invalid opportunity audit record at line {line_number}: {exc}"
                ) from exc
            if record.record_id in seen:
                raise RuntimeError(f"duplicate opportunity audit record: {record.record_id}")
            seen.add(record.record_id)
            records.append(record)
        return tuple(records)

    def metrics(self) -> OpportunityAuditMetrics:
        records = self.read_all()
        material = [
            record
            for record in records
            if record.outcome != OpportunityOutcome.NO_MATERIAL_MOVE
        ]
        return OpportunityAuditMetrics(
            material_opportunities=len(material),
            captured=sum(record.outcome == OpportunityOutcome.CAPTURED for record in material),
            missed_flat=sum(record.outcome == OpportunityOutcome.MISSED_FLAT for record in material),
            wrong_direction=sum(
                record.outcome == OpportunityOutcome.WRONG_DIRECTION for record in material
            ),
            blocked_safety=sum(
                record.outcome == OpportunityOutcome.BLOCKED_SAFETY for record in material
            ),
        )


class MissedOpportunityAuditor:
    """Ex-post live auditor for false negatives without leaking future data into decisions."""

    def __init__(
        self,
        store: OpportunityAuditStore,
        *,
        policy: OpportunityAuditPolicy | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or OpportunityAuditPolicy()
        self._pending: dict[str, _PendingOpportunity] = {}
        self._known_ids = {record.record_id for record in store.read_all()}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def register_scan(self, scan: MarketScanResult) -> int:
        added = 0
        for candidate in scan.candidates:
            pending = self._from_candidate(candidate)
            if pending is None:
                continue
            if pending.record_id in self._known_ids or pending.record_id in self._pending:
                continue
            self._pending[pending.record_id] = pending
            added += 1
        return added

    def on_closed_candles(
        self,
        candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle],
    ) -> tuple[OpportunityAuditRecord, ...]:
        if any(not candle.closed for candle in candles):
            raise ValueError("opportunity audit requires closed candles")
        resolved: list[OpportunityAuditRecord] = []
        for candle in sorted(candles, key=lambda item: item.close_time):
            matching = [
                record_id
                for record_id, pending in self._pending.items()
                if pending.symbol == candle.symbol and pending.timeframe == candle.timeframe
            ]
            for record_id in matching:
                pending = self._pending[record_id]
                if candle.close_time <= pending.decision_time:
                    continue
                pending.bars_seen += 1
                if pending.bars_seen < self.policy.horizon_bars:
                    continue
                record = self._resolve(pending, candle)
                if self.store.append(record):
                    self._known_ids.add(record.record_id)
                    resolved.append(record)
                del self._pending[record_id]
        return tuple(resolved)

    def _from_candidate(self, candidate: ScanCandidate) -> _PendingOpportunity | None:
        if candidate.data_quality is not None and not candidate.data_quality.safe_for_decision:
            return None
        candles = candidate.context.candles
        if len(candles) < self.policy.atr_period + 1:
            return None
        atr = _atr(candles, self.policy.atr_period)
        if atr <= 0:
            return None
        latest = candles[-1]
        safety_allowed = candidate.agent_policy is None or candidate.agent_policy.allowed
        record_id = (
            f"opportunity:{candidate.context.correlation_id}:"
            f"{candidate.context.created_at.isoformat()}"
        )
        return _PendingOpportunity(
            record_id=record_id,
            decision_time=candidate.context.created_at,
            symbol=candidate.context.symbol,
            timeframe=candidate.context.decision_timeframe,
            entry_price=latest.close,
            atr=atr,
            raw_intent=candidate.memo.intent,
            memo_confidence=candidate.memo.confidence,
            safety_allowed=safety_allowed,
        )

    def _resolve(
        self,
        pending: _PendingOpportunity,
        candle: NormalizedCandle,
    ) -> OpportunityAuditRecord:
        move = candle.close - pending.entry_price
        move_atr = float(move / pending.atr)
        if abs(move_atr) < self.policy.min_move_atr_multiple:
            realized_direction = SignalIntent.FLAT
            outcome = OpportunityOutcome.NO_MATERIAL_MOVE
        else:
            realized_direction = SignalIntent.LONG if move_atr > 0 else SignalIntent.SHORT
            if not pending.safety_allowed:
                outcome = OpportunityOutcome.BLOCKED_SAFETY
            elif pending.raw_intent == SignalIntent.FLAT:
                outcome = OpportunityOutcome.MISSED_FLAT
            elif pending.raw_intent != realized_direction:
                outcome = OpportunityOutcome.WRONG_DIRECTION
            else:
                outcome = OpportunityOutcome.CAPTURED
        return OpportunityAuditRecord(
            record_id=pending.record_id,
            decision_time=pending.decision_time,
            resolved_time=candle.close_time,
            symbol=pending.symbol,
            timeframe=pending.timeframe,
            raw_intent=pending.raw_intent,
            realized_direction=realized_direction,
            move_atr_multiple=move_atr,
            outcome=outcome,
            memo_confidence=pending.memo_confidence,
        )


def _atr(candles: tuple[NormalizedCandle, ...], period: int) -> Decimal:
    window = candles[-(period + 1) :]
    true_ranges: list[Decimal] = []
    for previous, current in zip(window, window[1:], strict=True):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    if not true_ranges:
        return Decimal(0)
    return sum(true_ranges, Decimal(0)) / Decimal(len(true_ranges))
