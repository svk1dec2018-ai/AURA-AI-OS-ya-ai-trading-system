from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from aura.research.lifecycle import (
    ActorType,
    EvidenceKind,
    GovernanceError,
    StrategyGovernance,
    StrategyStage,
    StrategyVersion,
    ValidationEvidence,
)


class ResearchOutcome(str, Enum):
    PAPER_VALIDATED = "paper_validated"
    REJECTED = "rejected"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ResearchHypothesis(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypothesis_id: str = Field(min_length=1)
    thesis: str = Field(min_length=1)
    market_scope: tuple[str, ...]
    timeframe_scope: tuple[str, ...]
    parent_strategy_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True, frozen=True)
class ResearchBudget:
    max_candidates: int = 10
    max_failed_candidates: int = 8

    def __post_init__(self) -> None:
        if self.max_candidates <= 0 or self.max_failed_candidates < 0:
            raise ValueError("invalid research budget")


class CandidateGenerator(Protocol):
    async def generate(
        self,
        hypothesis: ResearchHypothesis,
        *,
        feedback: tuple[str, ...],
        candidate_index: int,
    ) -> StrategyVersion: ...


class ResearchEvaluator(Protocol):
    kind: EvidenceKind

    async def evaluate(
        self,
        strategy: StrategyVersion,
        hypothesis: ResearchHypothesis,
    ) -> ValidationEvidence: ...


@dataclass(slots=True, frozen=True)
class CandidateTrace:
    strategy: StrategyVersion
    outcome: str
    feedback: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class AutonomousResearchResult:
    outcome: ResearchOutcome
    selected_strategy: StrategyVersion | None
    traces: tuple[CandidateTrace, ...]
    generated_candidates: int
    failed_candidates: int


class AutonomousResearchLoop:
    """Bounded self-improvement loop that can reach paper validation, never live approval.

    AI may generate new immutable candidate versions and learn from measured
    failures. Promotions are evidence-driven. The loop deliberately stops at
    PAPER_VALIDATED; `StrategyGovernance` still requires a human actor for the
    final APPROVED stage.
    """

    _ORDER = (
        EvidenceKind.BACKTEST,
        EvidenceKind.WALK_FORWARD,
        EvidenceKind.MONTE_CARLO,
        EvidenceKind.PAPER_TRADING,
    )

    def __init__(
        self,
        *,
        generator: CandidateGenerator,
        evaluators: tuple[ResearchEvaluator, ...],
        governance: StrategyGovernance | None = None,
        budget: ResearchBudget | None = None,
    ) -> None:
        self.generator = generator
        self.governance = governance or StrategyGovernance()
        self.budget = budget or ResearchBudget()
        by_kind = {evaluator.kind: evaluator for evaluator in evaluators}
        missing = [kind.value for kind in self._ORDER if kind not in by_kind]
        if missing:
            raise ValueError(f"missing research evaluators: {', '.join(missing)}")
        self.evaluators = by_kind

    async def run(self, hypothesis: ResearchHypothesis) -> AutonomousResearchResult:
        feedback: tuple[str, ...] = ()
        traces: list[CandidateTrace] = []
        failed = 0

        for candidate_index in range(self.budget.max_candidates):
            if failed > self.budget.max_failed_candidates:
                break
            strategy = await self.generator.generate(
                hypothesis,
                feedback=feedback,
                candidate_index=candidate_index,
            )
            if strategy.stage != StrategyStage.RESEARCH:
                raise GovernanceError("generated candidate must start at RESEARCH stage")

            candidate_feedback: list[str] = []
            rejected = False
            for kind in self._ORDER:
                evidence = await self.evaluators[kind].evaluate(strategy, hypothesis)
                if evidence.kind != kind:
                    raise GovernanceError(
                        f"evaluator for {kind.value} returned {evidence.kind.value} evidence"
                    )
                strategy = strategy.with_evidence(evidence)
                if not evidence.passed:
                    candidate_feedback.append(
                        f"{kind.value} failed: {evidence.notes or evidence.artifact_hash}"
                    )
                    strategy = self.governance.promote(
                        strategy,
                        StrategyStage.REJECTED,
                        ActorType.SYSTEM,
                    )
                    failed += 1
                    rejected = True
                    break

                target = {
                    EvidenceKind.BACKTEST: StrategyStage.BACKTEST_VALIDATED,
                    EvidenceKind.MONTE_CARLO: StrategyStage.ROBUSTNESS_VALIDATED,
                    EvidenceKind.PAPER_TRADING: StrategyStage.PAPER_VALIDATED,
                }.get(kind)
                # WALK_FORWARD evidence is accumulated together with Monte Carlo
                # before the ROBUSTNESS_VALIDATED promotion.
                if target is not None:
                    strategy = self.governance.promote(strategy, target, ActorType.SYSTEM)

            if rejected:
                feedback = tuple(candidate_feedback)
                traces.append(
                    CandidateTrace(
                        strategy=strategy,
                        outcome="rejected",
                        feedback=feedback,
                    )
                )
                continue

            if strategy.stage != StrategyStage.PAPER_VALIDATED:
                raise GovernanceError(
                    f"autonomous loop ended candidate at unexpected stage {strategy.stage.value}"
                )
            traces.append(
                CandidateTrace(
                    strategy=strategy,
                    outcome="paper_validated",
                    feedback=(),
                )
            )
            return AutonomousResearchResult(
                outcome=ResearchOutcome.PAPER_VALIDATED,
                selected_strategy=strategy,
                traces=tuple(traces),
                generated_candidates=candidate_index + 1,
                failed_candidates=failed,
            )

        return AutonomousResearchResult(
            outcome=ResearchOutcome.BUDGET_EXHAUSTED,
            selected_strategy=None,
            traces=tuple(traces),
            generated_candidates=len(traces),
            failed_candidates=failed,
        )
