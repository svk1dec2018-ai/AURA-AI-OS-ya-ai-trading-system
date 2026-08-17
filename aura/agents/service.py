from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.core.pipeline import DecisionPipeline, DecisionResult
from aura.data.quality import CandleQualityGate, DataQualityReport
from aura.domain.models import PortfolioSnapshot, SignalIntent, StrategySignal


@dataclass(slots=True, frozen=True)
class MultiAgentDecisionOutcome:
    round: AgentRound
    memo: CEODecisionMemo
    governed_result: DecisionResult | None
    data_quality_report: DataQualityReport | None = None


class MultiAgentDecisionService:
    """Data quality -> concurrent specialists -> CEO -> independent risk path."""

    strategy_id = "aura.multi_agent.ceo.v1"

    def __init__(
        self,
        *,
        orchestrator: MultiAgentOrchestrator,
        ceo: CEOAggregator,
        decision_pipeline: DecisionPipeline,
        data_quality_gate: CandleQualityGate | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.ceo = ceo
        self.decision_pipeline = decision_pipeline
        self.data_quality_gate = data_quality_gate

    async def evaluate(
        self,
        *,
        context: AgentContext,
        portfolio: PortfolioSnapshot,
        day_start_equity: Decimal,
        venue: str,
        requested_quantity: Decimal,
        current_position_quantity: Decimal = Decimal(0),
    ) -> MultiAgentDecisionOutcome:
        quality_report: DataQualityReport | None = None
        if self.data_quality_gate is not None:
            quality_report = self.data_quality_gate.assess(
                context.candles,
                decision_time=context.created_at,
            )
            if not quality_report.safe_for_decision:
                round_result = AgentRound(
                    correlation_id=context.correlation_id,
                    evidence=(),
                    failures=(),
                    started_at=context.created_at,
                    completed_at=context.created_at,
                )
                issue_names = ", ".join(issue.issue_type.value for issue in quality_report.issues)
                memo = CEODecisionMemo(
                    correlation_id=context.correlation_id,
                    intent=SignalIntent.FLAT,
                    confidence=0.0,
                    supporting_agents=(),
                    opposing_agents=(),
                    abstaining_agents=(),
                    risk_flags=("market_data_quality_block",),
                    rationale=f"market data quality gate blocked intelligence round: {issue_names}",
                    quorum_met=False,
                    generated_at=context.created_at,
                )
                return MultiAgentDecisionOutcome(
                    round=round_result,
                    memo=memo,
                    governed_result=None,
                    data_quality_report=quality_report,
                )

        round_result = await self.orchestrator.run_round(context)
        memo = self.ceo.synthesize(round_result)
        if not memo.quorum_met or memo.intent == SignalIntent.FLAT:
            return MultiAgentDecisionOutcome(
                round=round_result,
                memo=memo,
                governed_result=None,
                data_quality_report=quality_report,
            )

        signal = StrategySignal(
            strategy_id=self.strategy_id,
            symbol=context.symbol,
            intent=memo.intent,
            confidence=memo.confidence,
            reference_price=context.candles[-1].close,
            generated_at=context.candles[-1].close_time,
            reason=memo.rationale,
        )
        governed = self.decision_pipeline.evaluate_signal(
            signal=signal,
            portfolio=portfolio,
            day_start_equity=day_start_equity,
            venue=venue,
            requested_quantity=requested_quantity,
            current_position_quantity=current_position_quantity,
        )
        return MultiAgentDecisionOutcome(
            round=round_result,
            memo=memo,
            governed_result=governed,
            data_quality_report=quality_report,
        )
