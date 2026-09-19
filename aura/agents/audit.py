from __future__ import annotations

from enum import Enum

from aura.agents.deliberation import DeliberationMemo
from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.agents.risk_policy import AgentPolicyDecision
from aura.data.quality import DataQualityReport
from aura.lineage.decision import DecisionLineageRecord
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
        data_quality: DataQualityReport | None = None,
        agent_policy: AgentPolicyDecision | None = None,
        lineage: DecisionLineageRecord | None = None,
    ) -> WalEvent:
        if round_result.correlation_id != context.correlation_id:
            raise ValueError("agent round correlation_id does not match context")
        if memo.correlation_id != context.correlation_id:
            raise ValueError("CEO memo correlation_id does not match context")

        effective_lineage = lineage or DecisionLineageRecord.build(
            context=context,
            round_result=round_result,
            memo=memo,
            data_quality=data_quality,
            agent_policy=agent_policy,
            deliberation=deliberation,
        )
        if not effective_lineage.verify(
            context=context,
            round_result=round_result,
            memo=memo,
            data_quality=data_quality,
            agent_policy=agent_policy,
            deliberation=deliberation,
        ):
            raise ValueError("agent audit lineage does not match decision payload")

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
            "data_quality": _data_quality_payload(data_quality),
            "agent_policy": (
                agent_policy.model_dump(mode="json") if agent_policy is not None else None
            ),
            "lineage": effective_lineage.model_dump(mode="json"),
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


def _data_quality_payload(report: DataQualityReport | None) -> dict | None:
    if report is None:
        return None
    return {
        "bars_checked": report.bars_checked,
        "safe_for_decision": report.safe_for_decision,
        "issues": [item.model_dump(mode="json") for item in report.issues],
    }
