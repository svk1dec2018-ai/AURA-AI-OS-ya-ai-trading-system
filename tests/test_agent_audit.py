from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aura.agents.audit import AgentAuditEventType, AgentAuditJournal
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    AgentRound,
    CEODecisionMemo,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.lineage.decision import DecisionLineageRecord
from aura.lineage.replay import DecisionLineageMismatch, DecisionLineageReplayVerifier
from aura.persistence.wal import JsonlWriteAheadLog


def _decision_objects(*, metadata: dict | None = None):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="X",
        venue="TEST",
        timeframe="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
        open=Decimal(100),
        high=Decimal(102),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(100),
        closed=True,
    )
    context = AgentContext(
        correlation_id="round-1",
        symbol="X",
        decision_timeframe="5m",
        candles=(candle,),
        created_at=candle.close_time,
        metadata=metadata or {"mode": "paper"},
    )
    evidence = AgentEvidence(
        agent_id="technical:model-a",
        role=AgentRole.TECHNICAL,
        intent=SignalIntent.LONG,
        confidence=0.8,
        thesis="trend continuation",
        sources=(
            EvidenceSource(
                source_id="market:X:5m",
                source_type=EvidenceSourceType.MARKET_DATA,
                observed_at=candle.close_time,
                trust_score=1.0,
            ),
        ),
        generated_at=candle.close_time,
    )
    round_result = AgentRound(
        correlation_id=context.correlation_id,
        evidence=(evidence,),
        started_at=candle.close_time,
        completed_at=candle.close_time,
    )
    memo = CEODecisionMemo(
        correlation_id=context.correlation_id,
        intent=SignalIntent.FLAT,
        confidence=0.0,
        supporting_agents=(),
        opposing_agents=(),
        abstaining_agents=(evidence.agent_id,),
        risk_flags=(),
        rationale="quorum not met",
        quorum_met=False,
        generated_at=candle.close_time,
    )
    return context, round_result, memo


def test_agent_round_is_persisted_with_context_ceo_and_lineage(tmp_path: Path) -> None:
    context, round_result, memo = _decision_objects()
    wal = JsonlWriteAheadLog(tmp_path / "agent-audit.wal", fsync=False)
    event = AgentAuditJournal(wal).record_round(
        context=context,
        round_result=round_result,
        memo=memo,
    )

    assert event.event_type == AgentAuditEventType.ROUND_COMPLETED.value
    restored = wal.read_all()[0]
    assert restored.correlation_id == "round-1"
    assert restored.payload["context"]["symbol"] == "X"
    assert restored.payload["round"]["evidence"][0]["agent_id"] == "technical:model-a"
    assert restored.payload["memo"]["rationale"] == "quorum not met"
    lineage = DecisionLineageRecord.model_validate(restored.payload["lineage"])
    assert lineage.verify_hash()
    assert lineage.source_ids == ("market:X:5m",)


def test_replay_verifier_accepts_exact_decision_and_rejects_changed_context(
    tmp_path: Path,
) -> None:
    context, round_result, memo = _decision_objects()
    wal = JsonlWriteAheadLog(tmp_path / "agent-audit.wal", fsync=False)
    event = AgentAuditJournal(wal).record_round(
        context=context,
        round_result=round_result,
        memo=memo,
    )
    exact = DecisionLineageRecord.build(
        context=context,
        round_result=round_result,
        memo=memo,
        data_quality=None,
        agent_policy=None,
        deliberation=None,
    )
    verifier = DecisionLineageReplayVerifier()
    stored = verifier.verify_event(event, exact)
    assert stored.lineage_hash == exact.lineage_hash

    changed_context, changed_round, changed_memo = _decision_objects(
        metadata={"mode": "paper", "regime": "chop"}
    )
    changed = DecisionLineageRecord.build(
        context=changed_context,
        round_result=changed_round,
        memo=changed_memo,
        data_quality=None,
        agent_policy=None,
        deliberation=None,
    )
    with pytest.raises(DecisionLineageMismatch, match="lineage mismatch"):
        verifier.verify_event(event, changed)
