from __future__ import annotations

from enum import Enum

from aura.agents.deliberation import DeliberationMemo
from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.persistence.wal import JsonlWriteAheadLog, WalEvent


class AgentAuditEventType(str, Enum):
    ROUND_COMPLETED = "agent.round.completed"


class AgentAuditJournal:
    """Persist complete point-in-time multi-agent evidence and deliberation rounds."""

    def __init__(self, wal: JsonlWriteAheadLog) -> None:
        self.wal = wal

    def record_round(
        self,
        *,
        context: AgentContext,
        round_result: AgentRound,
        memo: CEODecisionMemo,
        deliberation: DeliberationMemo | None = None,
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
            "deliberation": _deliberation_payload(deliberation),
        }
        return self.wal.append(
            event_type=AgentAuditEventType.ROUND_COMPLETED.value,
            payload=payload,
            correlation_id=context.correlation_id,
        )


def _deliberation_payload(deliberation: DeliberationMemo | None) -> dict | None:
    if deliberation is None:
        return None
    return {
        "bull_case": deliberation.bull_case.model_dump(mode="json"),
        "bear_case": deliberation.bear_case.model_dump(mode="json"),
        "neutral_arguments": list(deliberation.neutral_arguments),
        "counterfactuals": [
            item.model_dump(mode="json") for item in deliberation.counterfactuals
        ],
        "disagreement_ratio": deliberation.disagreement_ratio,
        "evidence_count": deliberation.evidence_count,
    }
