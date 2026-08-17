from __future__ import annotations

from enum import Enum

from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.persistence.wal import JsonlWriteAheadLog, WalEvent


class AgentAuditEventType(str, Enum):
    ROUND_COMPLETED = "agent.round.completed"


class AgentAuditJournal:
    """Persist complete point-in-time multi-agent evidence rounds.

    This audit stream is separate from execution authority. It records what the
    intelligence layer saw and concluded so later trade/skip decisions can be
    reconstructed without giving agents any financial mutation privileges.
    """

    def __init__(self, wal: JsonlWriteAheadLog) -> None:
        self.wal = wal

    def record_round(
        self,
        *,
        context: AgentContext,
        round_result: AgentRound,
        memo: CEODecisionMemo,
    ) -> WalEvent:
        if round_result.correlation_id != context.correlation_id:
            raise ValueError("agent round correlation_id does not match context")
        if memo.correlation_id != context.correlation_id:
            raise ValueError("CEO memo correlation_id does not match context")

        payload = {
            "context": {
                "symbol": context.symbol,
                "decision_timeframe": context.decision_timeframe,
                "created_at": context.created_at.isoformat(),
                "latest_candle_close": context.candles[-1].close_time.isoformat(),
                "bars": len(context.candles),
                "metadata": context.metadata,
            },
            "round": round_result.model_dump(mode="json"),
            "memo": memo.model_dump(mode="json"),
        }
        return self.wal.append(
            event_type=AgentAuditEventType.ROUND_COMPLETED.value,
            payload=payload,
            correlation_id=context.correlation_id,
        )
