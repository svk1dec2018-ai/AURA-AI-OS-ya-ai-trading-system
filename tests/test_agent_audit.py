from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
from aura.persistence.wal import JsonlWriteAheadLog


def test_agent_round_is_persisted_with_context_and_ceo_memo(tmp_path: Path) -> None:
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
        metadata={"mode": "paper"},
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
