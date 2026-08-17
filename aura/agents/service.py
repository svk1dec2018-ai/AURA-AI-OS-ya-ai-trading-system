from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.core.pipeline import DecisionPipeline, DecisionResult
from aura.domain.models import PortfolioSnapshot, SignalIntent, StrategySignal


@dataclass(slots=True, frozen=True)
class MultiAgentDecisionOutcome:
    round: AgentRound
    memo: CEODecisionMemo
    governed_result: DecisionResult | None


class MultiAgentDecisionService:
    """Concurrent specialists -> CEO memo -> shared independent risk path."""

    strategy_id = "aura.multi_agent.ceo.v1"

    def __init__(
        self,
        *,
        orchestrator: MultiAgentOrchestrator,
        ceo: CEOAggregator,
        decision_pipeline: DecisionPipeline,
    ) -> None:
        self.orchestrator = orchestrator
        self.ceo = ceo
        self.decision_pipeline = decision_pipeline

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
        round_result = await self.orchestrator.run_round(context)
        memo = self.ceo.synthesize(round_result)
        if not memo.quorum_met or memo.intent == SignalIntent.FLAT:
            return MultiAgentDecisionOutcome(
                round=round_result,
                memo=memo,
                governed_result=None,
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
        )
