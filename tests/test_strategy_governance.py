import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from aura.persistence.wal import CorruptWalError
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


def advance_to_paper(
    registry: StrategyRegistry,
) -> tuple[StrategyGovernance, StrategyVersion]:
    governance = StrategyGovernance()
    strategy = StrategyVersion("alpha", "1.0.0", "code-hash")
    assert registry.register(strategy)

    strategy = strategy.with_evidence(passed(EvidenceKind.BACKTEST))
    strategy = governance.promote(strategy, StrategyStage.BACKTEST_VALIDATED, ActorType.AI)
    assert registry.save_transition(strategy, actor=ActorType.AI)

    strategy = strategy.with_evidence(passed(EvidenceKind.WALK_FORWARD))
    strategy = strategy.with_evidence(passed(EvidenceKind.MONTE_CARLO))
    strategy = governance.promote(strategy, StrategyStage.ROBUSTNESS_VALIDATED, ActorType.AI)
    assert registry.save_transition(strategy, actor=ActorType.AI)

    strategy = strategy.with_evidence(passed(EvidenceKind.PAPER_TRADING))
    strategy = governance.promote(strategy, StrategyStage.PAPER_VALIDATED, ActorType.SYSTEM)
    assert registry.save_transition(strategy, actor=ActorType.SYSTEM)
    return governance, strategy


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
    assert not can_deploy_live(approved)


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


def test_human_approval_receipt_survives_restart_and_is_revoked_on_retirement(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "strategy-registry.jsonl"
    registry = StrategyRegistry(journal_path)
    governance, paper_strategy = advance_to_paper(registry)

    approved = governance.promote(
        paper_strategy,
        StrategyStage.APPROVED,
        ActorType.HUMAN,
    )
    assert not can_deploy_live(approved)
    assert registry.save_transition(approved, actor=ActorType.HUMAN)
    assert not registry.save_transition(approved, actor=ActorType.HUMAN)
    assert can_deploy_live(approved, registry)

    recovered = StrategyRegistry(journal_path)
    assert recovered.recovered_events == 5
    assert recovered.get("alpha", "1.0.0") == approved
    assert can_deploy_live(approved, recovered)

    retired = governance.promote(approved, StrategyStage.RETIRED, ActorType.SYSTEM)
    assert recovered.save_transition(retired, actor=ActorType.SYSTEM)
    assert not can_deploy_live(retired, recovered)

    recovered_again = StrategyRegistry(journal_path)
    assert recovered_again.recovered_events == 6
    assert recovered_again.get("alpha", "1.0.0") == retired
    assert not can_deploy_live(retired, recovered_again)


def test_registry_revalidates_actor_and_transition_path() -> None:
    registry = StrategyRegistry()
    governance, paper_strategy = advance_to_paper(registry)
    approved = governance.promote(
        paper_strategy,
        StrategyStage.APPROVED,
        ActorType.HUMAN,
    )

    with pytest.raises(GovernanceError, match="human actor"):
        registry.save_transition(approved, actor=ActorType.AI)
    assert registry.get("alpha", "1.0.0") == paper_strategy
    assert not can_deploy_live(approved, registry)
    assert registry.save_transition(approved, actor=ActorType.HUMAN)
    assert not can_deploy_live(approved, registry)

    fresh_registry = StrategyRegistry()
    initial = StrategyVersion("beta", "1.0.0", "beta-code-hash")
    fresh_registry.register(initial)
    fabricated = replace(
        initial,
        stage=StrategyStage.APPROVED,
        updated_at=initial.updated_at + timedelta(microseconds=1),
    )
    with pytest.raises(GovernanceError, match="illegal promotion"):
        fresh_registry.save_transition(fabricated, actor=ActorType.HUMAN)


def test_registry_rejects_mutated_historical_evidence() -> None:
    registry = StrategyRegistry()
    _, paper_strategy = advance_to_paper(registry)
    tampered_evidence = replace(
        paper_strategy.evidence[0],
        artifact_hash="sha256:tampered",
    )
    tampered = replace(
        paper_strategy,
        evidence=(tampered_evidence, *paper_strategy.evidence[1:]),
        stage=StrategyStage.APPROVED,
        updated_at=paper_strategy.updated_at + timedelta(microseconds=1),
    )

    with pytest.raises(GovernanceError, match="changed or removed"):
        registry.save_transition(tampered, actor=ActorType.HUMAN)


def test_registry_fails_closed_on_corrupt_journal(tmp_path: Path) -> None:
    journal_path = tmp_path / "strategy-registry.jsonl"
    registry = StrategyRegistry(journal_path)
    registry.register(StrategyVersion("alpha", "1.0.0", "code-hash"))

    records = [json.loads(line) for line in journal_path.read_text().splitlines()]
    records[-1]["checksum"] = "0" * 64
    journal_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")

    with pytest.raises(CorruptWalError, match="checksum mismatch"):
        StrategyRegistry(journal_path)


def test_registry_fails_closed_on_invalid_evidence_type_with_valid_checksum(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "strategy-registry.jsonl"
    registry = StrategyRegistry(journal_path)
    advance_to_paper(registry)

    records = [json.loads(line) for line in journal_path.read_text().splitlines()]
    final_record = records[-1]
    final_record["event"]["payload"]["strategy"]["evidence"][0]["passed"] = "true"
    canonical_event = json.dumps(
        final_record["event"],
        sort_keys=True,
        separators=(",", ":"),
    )
    final_record["checksum"] = hashlib.sha256(canonical_event.encode()).hexdigest()
    journal_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")

    with pytest.raises(GovernanceError, match="invalid strategy transition event"):
        StrategyRegistry(journal_path)
