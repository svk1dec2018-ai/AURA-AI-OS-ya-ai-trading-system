from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aura.agents.deliberation import AdversarialDeliberationEngine, DeliberationMemo
from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.agents.risk_policy import AgentPolicyDecision, AgentRiskPolicy
from aura.data.quality import CandleQualityGate, DataQualityReport
from aura.domain.models import SignalIntent
from aura.lineage.decision import DecisionLineageRecord


@dataclass(slots=True, frozen=True)
class ScanCandidate:
    context: AgentContext
    round: AgentRound
    memo: CEODecisionMemo
    data_quality: DataQualityReport | None
    agent_policy: AgentPolicyDecision | None = None
    deliberation: DeliberationMemo | None = None
    lineage: DecisionLineageRecord | None = None

    @property
    def actionable(self) -> bool:
        return (
            self.memo.quorum_met
            and self.memo.intent != SignalIntent.FLAT
            and (self.agent_policy is None or self.agent_policy.allowed)
        )

    def verify_lineage(self) -> bool:
        if self.lineage is None:
            return False
        return self.lineage.verify(
            context=self.context,
            round_result=self.round,
            memo=self.memo,
            data_quality=self.data_quality,
            agent_policy=self.agent_policy,
            deliberation=self.deliberation,
        )


@dataclass(slots=True, frozen=True)
class MarketScanResult:
    candidates: tuple[ScanCandidate, ...]

    @property
    def opportunities(self) -> tuple[ScanCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.actionable)


class MultiMarketIntelligenceScanner:
    """Scan symbols/timeframes concurrently without granting execution authority.

    Every scan candidate carries a cryptographic lineage record covering the
    point-in-time market inputs, specialist evidence, data-quality result,
    deliberation, CEO synthesis and evidence-policy decision. The lineage is for
    reproducibility/audit only and grants no order or risk authority.
    """

    def __init__(
        self,
        *,
        orchestrator: MultiAgentOrchestrator,
        ceo: CEOAggregator,
        data_quality_gate: CandleQualityGate | None = None,
        agent_risk_policy: AgentRiskPolicy | None = None,
        deliberation_engine: AdversarialDeliberationEngine | None = None,
        max_concurrent_contexts: int = 20,
    ) -> None:
        if max_concurrent_contexts <= 0:
            raise ValueError("max_concurrent_contexts must be positive")
        self.orchestrator = orchestrator
        self.ceo = ceo
        self.data_quality_gate = data_quality_gate
        self.agent_risk_policy = agent_risk_policy
        self.deliberation_engine = deliberation_engine or AdversarialDeliberationEngine()
        self.max_concurrent_contexts = max_concurrent_contexts

    async def scan(self, contexts: list[AgentContext] | tuple[AgentContext, ...]) -> MarketScanResult:
        if not contexts:
            return MarketScanResult(candidates=())
        correlation_ids = [context.correlation_id for context in contexts]
        if len(correlation_ids) != len(set(correlation_ids)):
            raise ValueError("scan contexts require unique correlation_id values")

        semaphore = asyncio.Semaphore(self.max_concurrent_contexts)

        async def run_context(context: AgentContext) -> ScanCandidate:
            async with semaphore:
                return await self._scan_context(context)

        candidates = await asyncio.gather(*(run_context(context) for context in contexts))
        candidates.sort(
            key=lambda candidate: (
                not candidate.actionable,
                -candidate.memo.confidence,
                candidate.context.symbol,
                candidate.context.decision_timeframe,
            )
        )
        return MarketScanResult(candidates=tuple(candidates))

    async def _scan_context(self, context: AgentContext) -> ScanCandidate:
        quality_report: DataQualityReport | None = None
        if self.data_quality_gate is not None:
            quality_report = self.data_quality_gate.assess(
                context.candles,
                decision_time=context.created_at,
            )
            if not quality_report.safe_for_decision:
                empty_round = AgentRound(
                    correlation_id=context.correlation_id,
                    evidence=(),
                    failures=(),
                    started_at=context.created_at,
                    completed_at=context.created_at,
                )
                issue_names = ", ".join(issue.issue_type.value for issue in quality_report.issues)
                blocked_memo = CEODecisionMemo(
                    correlation_id=context.correlation_id,
                    intent=SignalIntent.FLAT,
                    confidence=0.0,
                    supporting_agents=(),
                    opposing_agents=(),
                    abstaining_agents=(),
                    risk_flags=("market_data_quality_block",),
                    rationale=f"market data quality gate blocked scan: {issue_names}",
                    quorum_met=False,
                    generated_at=context.created_at,
                )
                policy_decision = (
                    self.agent_risk_policy.evaluate(
                        round_result=empty_round,
                        memo=blocked_memo,
                    )
                    if self.agent_risk_policy is not None
                    else None
                )
                lineage = DecisionLineageRecord.build(
                    context=context,
                    round_result=empty_round,
                    memo=blocked_memo,
                    data_quality=quality_report,
                    agent_policy=policy_decision,
                    deliberation=None,
                )
                return ScanCandidate(
                    context=context,
                    round=empty_round,
                    memo=blocked_memo,
                    data_quality=quality_report,
                    agent_policy=policy_decision,
                    deliberation=None,
                    lineage=lineage,
                )

        round_result = await self.orchestrator.run_round(context)
        deliberation = self.deliberation_engine.deliberate(round_result)
        memo = self.ceo.synthesize(round_result, context=context)
        policy_decision = (
            self.agent_risk_policy.evaluate(round_result=round_result, memo=memo)
            if self.agent_risk_policy is not None
            else None
        )
        lineage = DecisionLineageRecord.build(
            context=context,
            round_result=round_result,
            memo=memo,
            data_quality=quality_report,
            agent_policy=policy_decision,
            deliberation=deliberation,
        )
        return ScanCandidate(
            context=context,
            round=round_result,
            memo=memo,
            data_quality=quality_report,
            agent_policy=policy_decision,
            deliberation=deliberation,
            lineage=lineage,
        )
