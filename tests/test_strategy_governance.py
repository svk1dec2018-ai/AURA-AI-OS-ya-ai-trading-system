import pytest

from aura.research.lifecycle import (
    ActorType,
    EvidenceKind,
    GovernanceError,
    StrategyGovernance,
    StrategyRegistry,
    StrategyStage,
    StrategyVersion,
    ValidationEvidence,
    can_deploy_live,
)


def passed(kind: EvidenceKind) -> ValidationEvidence:
    return ValidationEvidence(kind=kind, passed=True, artifact_hash=f"sha256:{kind.value}")


def test_ai_cannot_approve_strategy_for_live_deployment() -> None:
    governance = StrategyGovernance()
    strategy = StrategyVersion("alpha", "1.0.0", "code-hash")
    strategy = strategy.with_evidence(passed(EvidenceKind.BACKTEST))
    strategy = governance.promote(strategy, StrategyStage.BACKTEST_VALIDATED, ActorType.AI)
    strategy = strategy.with_evidence(passed(EvidenceKind.WALK_FORWARD))
    strategy = strategy.with_evidence(passed(EvidenceKind.MONTE_CARLO))
    strategy = governance.promote(strategy, StrategyStage.ROBUSTNESS_VALIDATED, ActorType.AI)
    strategy = strategy.with_evidence(passed(EvidenceKind.PAPER_TRADING))
    strategy = governance.promote(strategy, StrategyStage.PAPER_VALIDATED, ActorType.SYSTEM)

    with pytest.raises(GovernanceError, match="human actor"):
        governance.promote(strategy, StrategyStage.APPROVED, ActorType.AI)
    assert not can_deploy_live(strategy)

    approved = governance.promote(strategy, StrategyStage.APPROVED, ActorType.HUMAN)
    assert can_deploy_live(approved)


def test_missing_validation_evidence_blocks_promotion() -> None:
    governance = StrategyGovernance()
    strategy = StrategyVersion("alpha", "1.0.0", "code-hash")

    with pytest.raises(GovernanceError, match="BACKTEST"):
        governance.promote(strategy, StrategyStage.BACKTEST_VALIDATED, ActorType.AI)


def test_registry_prevents_code_replacement_under_same_version() -> None:
    registry = StrategyRegistry()
    registry.register(StrategyVersion("alpha", "1.0.0", "hash-a"))

    with pytest.raises(GovernanceError, match="different code"):
        registry.register(StrategyVersion("alpha", "1.0.0", "hash-b"))
