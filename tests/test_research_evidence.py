from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aura.research.evidence import build_robustness_evidence
from aura.research.lifecycle import (
    ActorType,
    EvidenceKind,
    GovernanceError,
    StrategyGovernance,
    StrategyStage,
    StrategyVersion,
    ValidationEvidence,
)
from aura.research.robustness import (
    RobustnessThresholds,
    bootstrap_monte_carlo,
    summarize_walk_forward,
)


def _backtest_evidence() -> ValidationEvidence:
    return ValidationEvidence(
        kind=EvidenceKind.BACKTEST,
        passed=True,
        artifact_hash="b" * 64,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_stable_metrics_create_passed_evidence_and_allow_robustness_promotion() -> None:
    thresholds = RobustnessThresholds(
        min_positive_fold_ratio=0.8,
        min_compounded_oos_return=0.05,
        max_probability_of_loss=0.2,
        max_p95_drawdown=0.15,
    )
    bundle = build_robustness_evidence(
        summarize_walk_forward([0.04, 0.03, 0.02, 0.05, 0.01]),
        bootstrap_monte_carlo(
            [0.01, 0.005, 0.008, -0.002, 0.012, 0.004, 0.006, -0.001],
            paths=400,
            block_size=2,
            seed=7,
        ),
        thresholds=thresholds,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert bundle.decision.approved
    assert bundle.walk_forward.passed
    assert bundle.monte_carlo.passed
    assert len(bundle.walk_forward.artifact_hash) == 64
    assert len(bundle.monte_carlo.artifact_hash) == 64

    governance = StrategyGovernance()
    strategy = StrategyVersion(
        strategy_id="candidate",
        version="1.0.0",
        content_hash="c" * 64,
    )
    strategy = strategy.with_evidence(_backtest_evidence())
    strategy = governance.promote(strategy, StrategyStage.BACKTEST_VALIDATED, ActorType.SYSTEM)
    strategy = strategy.with_evidence(bundle.walk_forward)
    strategy = strategy.with_evidence(bundle.monte_carlo)
    strategy = governance.promote(strategy, StrategyStage.ROBUSTNESS_VALIDATED, ActorType.SYSTEM)
    assert strategy.stage == StrategyStage.ROBUSTNESS_VALIDATED


def test_unstable_metrics_create_failed_evidence_and_block_promotion() -> None:
    bundle = build_robustness_evidence(
        summarize_walk_forward([0.03, -0.08, -0.02, 0.01, -0.04]),
        bootstrap_monte_carlo(
            [-0.03, 0.01, -0.04, 0.005, -0.02, 0.015, -0.01],
            paths=400,
            block_size=2,
            seed=9,
        ),
        thresholds=RobustnessThresholds(
            min_positive_fold_ratio=0.6,
            min_compounded_oos_return=0.0,
            max_probability_of_loss=0.4,
            max_p95_drawdown=0.2,
        ),
    )
    assert not bundle.decision.approved
    assert not bundle.walk_forward.passed or not bundle.monte_carlo.passed

    governance = StrategyGovernance()
    strategy = StrategyVersion(
        strategy_id="candidate",
        version="1.0.0",
        content_hash="c" * 64,
    )
    strategy = strategy.with_evidence(_backtest_evidence())
    strategy = governance.promote(strategy, StrategyStage.BACKTEST_VALIDATED, ActorType.SYSTEM)
    strategy = strategy.with_evidence(bundle.walk_forward)
    strategy = strategy.with_evidence(bundle.monte_carlo)
    with pytest.raises(GovernanceError, match="missing passed evidence"):
        governance.promote(strategy, StrategyStage.ROBUSTNESS_VALIDATED, ActorType.AI)
