from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aura.research.autonomy import (
    AutonomousResearchLoop,
    ResearchBudget,
    ResearchHypothesis,
    ResearchOutcome,
)
from aura.research.lifecycle import (
    ActorType,
    EvidenceKind,
    GovernanceError,
    StrategyGovernance,
    StrategyStage,
    StrategyVersion,
    ValidationEvidence,
)


class Generator:
    def __init__(self) -> None:
        self.feedback_seen: list[tuple[str, ...]] = []

    async def generate(self, hypothesis, *, feedback, candidate_index):
        self.feedback_seen.append(feedback)
        return StrategyVersion(
            strategy_id=f"candidate-{candidate_index}",
            version="1.0.0",
            content_hash=(str(candidate_index % 10) * 64),
        )


class Evaluator:
    def __init__(self, kind: EvidenceKind, fail_first_candidate: bool = False) -> None:
        self.kind = kind
        self.fail_first_candidate = fail_first_candidate

    async def evaluate(self, strategy, hypothesis):
        should_fail = self.fail_first_candidate and strategy.strategy_id == "candidate-0"
        return ValidationEvidence(
            kind=self.kind,
            passed=not should_fail,
            artifact_hash=(self.kind.value[0].lower() * 64),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            notes="measured failure" if should_fail else "measured pass",
        )


def _evaluators(*, fail_first_backtest: bool = False):
    return tuple(
        Evaluator(kind, fail_first_candidate=(fail_first_backtest and kind == EvidenceKind.BACKTEST))
        for kind in (
            EvidenceKind.BACKTEST,
            EvidenceKind.WALK_FORWARD,
            EvidenceKind.MONTE_CARLO,
            EvidenceKind.PAPER_TRADING,
        )
    )


def _hypothesis():
    return ResearchHypothesis(
        hypothesis_id="h-1",
        thesis="regime-aware XAUUSD momentum with volume confirmation",
        market_scope=("XAUUSD",),
        timeframe_scope=("1m", "5m"),
    )


@pytest.mark.asyncio
async def test_loop_learns_from_failed_candidate_then_reaches_paper_validated() -> None:
    generator = Generator()
    loop = AutonomousResearchLoop(
        generator=generator,
        evaluators=_evaluators(fail_first_backtest=True),
        budget=ResearchBudget(max_candidates=3, max_failed_candidates=2),
    )

    result = await loop.run(_hypothesis())
    assert result.outcome == ResearchOutcome.PAPER_VALIDATED
    assert result.selected_strategy is not None
    assert result.selected_strategy.stage == StrategyStage.PAPER_VALIDATED
    assert result.generated_candidates == 2
    assert result.failed_candidates == 1
    assert generator.feedback_seen[0] == ()
    assert "BACKTEST failed" in generator.feedback_seen[1][0]


def test_human_approval_is_still_required_after_autonomous_paper_validation() -> None:
    strategy = StrategyVersion(
        strategy_id="paper-ready",
        version="1",
        content_hash="a" * 64,
        stage=StrategyStage.PAPER_VALIDATED,
        evidence=tuple(
            ValidationEvidence(
                kind=kind,
                passed=True,
                artifact_hash=kind.value[0].lower() * 64,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            for kind in (
                EvidenceKind.BACKTEST,
                EvidenceKind.WALK_FORWARD,
                EvidenceKind.MONTE_CARLO,
                EvidenceKind.PAPER_TRADING,
            )
        ),
    )
    governance = StrategyGovernance()
    with pytest.raises(GovernanceError, match="human actor"):
        governance.promote(strategy, StrategyStage.APPROVED, ActorType.AI)
