from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum


class GovernanceError(RuntimeError):
    pass


class ActorType(str, Enum):
    AI = "AI"
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"


class EvidenceKind(str, Enum):
    BACKTEST = "BACKTEST"
    WALK_FORWARD = "WALK_FORWARD"
    MONTE_CARLO = "MONTE_CARLO"
    PAPER_TRADING = "PAPER_TRADING"


class StrategyStage(str, Enum):
    RESEARCH = "RESEARCH"
    BACKTEST_VALIDATED = "BACKTEST_VALIDATED"
    ROBUSTNESS_VALIDATED = "ROBUSTNESS_VALIDATED"
    PAPER_VALIDATED = "PAPER_VALIDATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


@dataclass(slots=True, frozen=True)
class ValidationEvidence:
    kind: EvidenceKind
    passed: bool
    artifact_hash: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_hash.strip():
            raise ValueError("artifact_hash is required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("evidence timestamp must be timezone-aware")


@dataclass(slots=True, frozen=True)
class StrategyVersion:
    strategy_id: str
    version: str
    content_hash: str
    stage: StrategyStage = StrategyStage.RESEARCH
    evidence: tuple[ValidationEvidence, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.version.strip() or not self.content_hash.strip():
            raise ValueError("strategy_id, version and content_hash are required")

    @property
    def identity(self) -> tuple[str, str]:
        return self.strategy_id, self.version

    def with_evidence(self, evidence: ValidationEvidence) -> StrategyVersion:
        if self.stage in {StrategyStage.APPROVED, StrategyStage.REJECTED, StrategyStage.RETIRED}:
            raise GovernanceError(f"cannot mutate evidence for terminal stage {self.stage}")
        return replace(
            self,
            evidence=(*self.evidence, evidence),
            updated_at=datetime.now(UTC),
        )

    def has_passed(self, kind: EvidenceKind) -> bool:
        return any(item.kind == kind and item.passed for item in self.evidence)


_REQUIRED_EVIDENCE: dict[StrategyStage, frozenset[EvidenceKind]] = {
    StrategyStage.BACKTEST_VALIDATED: frozenset({EvidenceKind.BACKTEST}),
    StrategyStage.ROBUSTNESS_VALIDATED: frozenset(
        {EvidenceKind.BACKTEST, EvidenceKind.WALK_FORWARD, EvidenceKind.MONTE_CARLO}
    ),
    StrategyStage.PAPER_VALIDATED: frozenset(
        {
            EvidenceKind.BACKTEST,
            EvidenceKind.WALK_FORWARD,
            EvidenceKind.MONTE_CARLO,
            EvidenceKind.PAPER_TRADING,
        }
    ),
    StrategyStage.APPROVED: frozenset(
        {
            EvidenceKind.BACKTEST,
            EvidenceKind.WALK_FORWARD,
            EvidenceKind.MONTE_CARLO,
            EvidenceKind.PAPER_TRADING,
        }
    ),
}

_ALLOWED_PROMOTIONS: dict[StrategyStage, frozenset[StrategyStage]] = {
    StrategyStage.RESEARCH: frozenset({StrategyStage.BACKTEST_VALIDATED, StrategyStage.REJECTED}),
    StrategyStage.BACKTEST_VALIDATED: frozenset(
        {StrategyStage.ROBUSTNESS_VALIDATED, StrategyStage.REJECTED}
    ),
    StrategyStage.ROBUSTNESS_VALIDATED: frozenset(
        {StrategyStage.PAPER_VALIDATED, StrategyStage.REJECTED}
    ),
    StrategyStage.PAPER_VALIDATED: frozenset({StrategyStage.APPROVED, StrategyStage.REJECTED}),
    StrategyStage.APPROVED: frozenset({StrategyStage.RETIRED}),
    StrategyStage.REJECTED: frozenset(),
    StrategyStage.RETIRED: frozenset(),
}


class StrategyGovernance:
    """Controls strategy promotion without allowing code mutation.

    Research automation may attach evidence and request promotions. Only a human
    actor can perform the final PAPER_VALIDATED -> APPROVED transition.
    """

    def promote(
        self,
        strategy: StrategyVersion,
        target: StrategyStage,
        actor: ActorType,
    ) -> StrategyVersion:
        if target not in _ALLOWED_PROMOTIONS[strategy.stage]:
            raise GovernanceError(f"illegal promotion {strategy.stage} -> {target}")
        if target == StrategyStage.APPROVED and actor != ActorType.HUMAN:
            raise GovernanceError("final live approval requires a human actor")

        required = _REQUIRED_EVIDENCE.get(target, frozenset())
        missing = sorted(kind.value for kind in required if not strategy.has_passed(kind))
        if missing:
            raise GovernanceError(f"missing passed evidence: {', '.join(missing)}")

        return replace(strategy, stage=target, updated_at=datetime.now(UTC))


class StrategyRegistry:
    """In-memory immutable-version registry suitable for a persistent adapter later."""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], StrategyVersion] = {}

    def register(self, strategy: StrategyVersion) -> None:
        existing = self._versions.get(strategy.identity)
        if existing is not None and existing.content_hash != strategy.content_hash:
            raise GovernanceError("strategy version identity cannot point to different code")
        self._versions[strategy.identity] = strategy

    def get(self, strategy_id: str, version: str) -> StrategyVersion:
        try:
            return self._versions[(strategy_id, version)]
        except KeyError as exc:
            raise KeyError(f"unknown strategy version: {strategy_id}@{version}") from exc

    def save_transition(self, strategy: StrategyVersion) -> None:
        existing = self.get(*strategy.identity)
        if existing.content_hash != strategy.content_hash:
            raise GovernanceError("strategy code hash changed during lifecycle transition")
        self._versions[strategy.identity] = strategy


def can_deploy_live(strategy: StrategyVersion) -> bool:
    """Live runtimes must call this gate before loading a strategy version."""
    return strategy.stage == StrategyStage.APPROVED
