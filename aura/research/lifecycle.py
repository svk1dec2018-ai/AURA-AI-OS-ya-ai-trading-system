from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from aura.persistence.wal import JsonlWriteAheadLog, WalEvent

_REGISTRY_SCHEMA_VERSION = 1
_REGISTRY_HEADER_EVENT = "strategy_registry_initialized"
_REGISTER_EVENT = "strategy_version_registered"
_TRANSITION_EVENT = "strategy_lifecycle_transitioned"


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
        for name, value in (("created_at", self.created_at), ("updated_at", self.updated_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"strategy {name} must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("strategy updated_at cannot precede created_at")

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
    """Immutable strategy registry with an optional durable lifecycle audit WAL.

    Registration always starts at RESEARCH. Every later state change is independently
    revalidated against the governance transition graph and records the responsible
    actor. An APPROVED value becomes deployable only when this registry contains the
    corresponding HUMAN approval transition; constructing an APPROVED dataclass is
    never sufficient.
    """

    def __init__(self, journal_path: Path | None = None) -> None:
        self._versions: dict[tuple[str, str], StrategyVersion] = {}
        self._human_approvals: set[tuple[str, str, str]] = set()
        self._transition_events: set[str] = set()
        self._last_transition_actor: dict[tuple[str, str], ActorType] = {}
        self.journal_path = journal_path
        self.recovered_events = 0
        self._wal = JsonlWriteAheadLog(journal_path) if journal_path is not None else None
        if self._wal is not None:
            self._initialize_or_replay()

    def register(self, strategy: StrategyVersion) -> bool:
        existing = self._versions.get(strategy.identity)
        if existing is not None:
            if existing.content_hash != strategy.content_hash:
                raise GovernanceError("strategy version identity cannot point to different code")
            if existing != strategy:
                raise GovernanceError("registered strategy version cannot be replaced")
            return False
        if strategy.stage != StrategyStage.RESEARCH or strategy.evidence:
            raise GovernanceError("new registry versions must start at RESEARCH without evidence")
        event_id = _registration_event_id(strategy)
        if self._wal is not None:
            event = self._wal.append(
                event_type=_REGISTER_EVENT,
                payload={
                    "registry_schema_version": _REGISTRY_SCHEMA_VERSION,
                    "strategy": _strategy_payload(strategy),
                },
                correlation_id=_strategy_correlation_id(strategy),
                event_id=event_id,
            )
            self._apply_registration_event(event)
        else:
            self._versions[strategy.identity] = strategy
        return True

    def get(self, strategy_id: str, version: str) -> StrategyVersion:
        try:
            return self._versions[(strategy_id, version)]
        except KeyError as exc:
            raise KeyError(f"unknown strategy version: {strategy_id}@{version}") from exc

    def save_transition(
        self,
        strategy: StrategyVersion,
        *,
        actor: ActorType,
    ) -> bool:
        existing = self.get(*strategy.identity)
        if existing.content_hash != strategy.content_hash:
            raise GovernanceError("strategy code hash changed during lifecycle transition")
        if existing == strategy:
            if self._last_transition_actor.get(strategy.identity) == actor:
                return False
            raise GovernanceError("strategy transition retry used a different actor")
        event_id = _transition_event_id(existing, strategy, actor)
        if event_id in self._transition_events:
            return False
        self._validate_transition(existing, strategy, actor)
        if self._wal is not None:
            event = self._wal.append(
                event_type=_TRANSITION_EVENT,
                payload={
                    "registry_schema_version": _REGISTRY_SCHEMA_VERSION,
                    "actor": actor.value,
                    "from_stage": existing.stage.value,
                    "strategy": _strategy_payload(strategy),
                },
                correlation_id=_strategy_correlation_id(strategy),
                event_id=event_id,
            )
            self._apply_transition_event(event)
        else:
            self._apply_transition(existing, strategy, actor, event_id)
        return True

    def is_human_approved(self, strategy: StrategyVersion) -> bool:
        stored = self._versions.get(strategy.identity)
        approval_key = (*strategy.identity, strategy.content_hash)
        return (
            self._wal is not None
            and stored == strategy
            and strategy.stage == StrategyStage.APPROVED
            and approval_key in self._human_approvals
        )

    def _initialize_or_replay(self) -> None:
        assert self._wal is not None
        events = self._wal.read_all()
        if not events:
            self._wal.append(
                event_type=_REGISTRY_HEADER_EVENT,
                payload={"registry_schema_version": _REGISTRY_SCHEMA_VERSION},
                correlation_id="strategy-registry",
                event_id="strategy-registry:initialized:v1",
            )
            return
        header = events[0]
        self._validate_schema(header)
        if (
            header.event_type != _REGISTRY_HEADER_EVENT
            or header.event_id != "strategy-registry:initialized:v1"
            or header.correlation_id != "strategy-registry"
        ):
            raise GovernanceError("strategy registry journal is missing its header")
        for event in events[1:]:
            self._validate_schema(event)
            if event.event_type == _REGISTER_EVENT:
                self._apply_registration_event(event)
            elif event.event_type == _TRANSITION_EVENT:
                self._apply_transition_event(event)
            else:
                raise GovernanceError(
                    f"unknown strategy registry event: {event.event_type}"
                )
            self.recovered_events += 1

    def _apply_registration_event(self, event: WalEvent) -> None:
        try:
            strategy = _strategy_from_payload(event.payload["strategy"])
        except Exception as exc:
            raise GovernanceError(f"invalid strategy registration event: {event.event_id}") from exc
        if event.event_id != _registration_event_id(strategy):
            raise GovernanceError(f"strategy registration event_id mismatch: {event.event_id}")
        if event.correlation_id != _strategy_correlation_id(strategy):
            raise GovernanceError(f"strategy registration correlation mismatch: {event.event_id}")
        if strategy.stage != StrategyStage.RESEARCH or strategy.evidence:
            raise GovernanceError("journaled strategy registration must begin at RESEARCH")
        existing = self._versions.get(strategy.identity)
        if existing is not None:
            raise GovernanceError(f"duplicate strategy registration event: {event.event_id}")
        self._versions[strategy.identity] = strategy

    def _apply_transition_event(self, event: WalEvent) -> None:
        try:
            strategy = _strategy_from_payload(event.payload["strategy"])
            actor = ActorType(str(event.payload["actor"]))
            from_stage = StrategyStage(str(event.payload["from_stage"]))
        except Exception as exc:
            raise GovernanceError(f"invalid strategy transition event: {event.event_id}") from exc
        existing = self.get(*strategy.identity)
        if existing.stage != from_stage:
            raise GovernanceError(f"strategy transition source mismatch: {event.event_id}")
        expected_id = _transition_event_id(existing, strategy, actor)
        if event.event_id != expected_id:
            raise GovernanceError(f"strategy transition event_id mismatch: {event.event_id}")
        if event.correlation_id != _strategy_correlation_id(strategy):
            raise GovernanceError(f"strategy transition correlation mismatch: {event.event_id}")
        if event.event_id in self._transition_events:
            raise GovernanceError(f"duplicate strategy transition event: {event.event_id}")
        self._validate_transition(existing, strategy, actor)
        self._apply_transition(existing, strategy, actor, event.event_id)

    @staticmethod
    def _validate_transition(
        existing: StrategyVersion,
        strategy: StrategyVersion,
        actor: ActorType,
    ) -> None:
        if strategy.identity != existing.identity:
            raise GovernanceError("strategy identity changed during lifecycle transition")
        if strategy.content_hash != existing.content_hash:
            raise GovernanceError("strategy code hash changed during lifecycle transition")
        if strategy.created_at != existing.created_at:
            raise GovernanceError("strategy created_at changed during lifecycle transition")
        if strategy.updated_at <= existing.updated_at:
            raise GovernanceError("strategy updated_at must advance during a transition")
        old_evidence = existing.evidence
        if strategy.evidence[: len(old_evidence)] != old_evidence:
            raise GovernanceError("existing validation evidence was changed or removed")
        if existing.stage in {
            StrategyStage.APPROVED,
            StrategyStage.REJECTED,
            StrategyStage.RETIRED,
        } and strategy.evidence != old_evidence:
            raise GovernanceError("validation evidence cannot be added after a terminal stage")
        candidate = replace(existing, evidence=strategy.evidence)
        validated = StrategyGovernance().promote(candidate, strategy.stage, actor)
        if validated.stage != strategy.stage:
            raise GovernanceError("strategy transition validation failed")

    def _apply_transition(
        self,
        existing: StrategyVersion,
        strategy: StrategyVersion,
        actor: ActorType,
        event_id: str,
    ) -> None:
        self._versions[strategy.identity] = strategy
        self._transition_events.add(event_id)
        self._last_transition_actor[strategy.identity] = actor
        approval_key = (*strategy.identity, strategy.content_hash)
        if strategy.stage == StrategyStage.APPROVED and actor == ActorType.HUMAN:
            self._human_approvals.add(approval_key)
        elif existing.stage == StrategyStage.APPROVED:
            self._human_approvals.discard(approval_key)

    @staticmethod
    def _validate_schema(event: WalEvent) -> None:
        if event.schema_version != 1:
            raise GovernanceError(f"unsupported WAL schema in event {event.event_id}")
        if event.created_at.tzinfo is None or event.created_at.utcoffset() is None:
            raise GovernanceError(f"naive event timestamp in event {event.event_id}")
        schema_version = event.payload.get("registry_schema_version")
        if type(schema_version) is not int or schema_version != _REGISTRY_SCHEMA_VERSION:
            raise GovernanceError(
                f"unsupported strategy registry schema in event {event.event_id}"
            )


def can_deploy_live(
    strategy: StrategyVersion,
    registry: StrategyRegistry | None = None,
) -> bool:
    """Require a durable HUMAN approval receipt, not merely an APPROVED field."""
    return registry is not None and registry.is_human_approved(strategy)


def _strategy_correlation_id(strategy: StrategyVersion) -> str:
    return f"{strategy.strategy_id}@{strategy.version}"


def _registration_event_id(strategy: StrategyVersion) -> str:
    return (
        f"strategy-register:{strategy.strategy_id}:{strategy.version}:"
        f"{strategy.content_hash}"
    )


def _transition_event_id(
    existing: StrategyVersion,
    strategy: StrategyVersion,
    actor: ActorType,
) -> str:
    return (
        f"strategy-transition:{strategy.strategy_id}:{strategy.version}:"
        f"{existing.stage.value}:{strategy.stage.value}:{actor.value}"
    )


def _strategy_payload(strategy: StrategyVersion) -> dict[str, object]:
    return {
        "strategy_id": strategy.strategy_id,
        "version": strategy.version,
        "content_hash": strategy.content_hash,
        "stage": strategy.stage.value,
        "evidence": [
            {
                "kind": item.kind.value,
                "passed": item.passed,
                "artifact_hash": item.artifact_hash,
                "created_at": item.created_at.isoformat(),
                "notes": item.notes,
            }
            for item in strategy.evidence
        ],
        "created_at": strategy.created_at.isoformat(),
        "updated_at": strategy.updated_at.isoformat(),
    }


def _strategy_from_payload(raw: object) -> StrategyVersion:
    if not isinstance(raw, dict):
        raise TypeError("strategy payload must be an object")
    raw_evidence = raw.get("evidence")
    if not isinstance(raw_evidence, list):
        raise TypeError("strategy evidence payload must be a list")
    evidence_items: list[ValidationEvidence] = []
    for item in raw_evidence:
        if not isinstance(item, dict):
            raise TypeError("strategy evidence payload contains a non-object")
        passed = item.get("passed")
        if not isinstance(passed, bool):
            raise TypeError("strategy evidence passed must be a boolean")
        evidence_items.append(
            ValidationEvidence(
                kind=EvidenceKind(_required_string(item, "kind")),
                passed=passed,
                artifact_hash=_required_string(item, "artifact_hash"),
                created_at=datetime.fromisoformat(_required_string(item, "created_at")),
                notes=_optional_string(item, "notes"),
            )
        )
    return StrategyVersion(
        strategy_id=_required_string(raw, "strategy_id"),
        version=_required_string(raw, "version"),
        content_hash=_required_string(raw, "content_hash"),
        stage=StrategyStage(_required_string(raw, "stage")),
        evidence=tuple(evidence_items),
        created_at=datetime.fromisoformat(_required_string(raw, "created_at")),
        updated_at=datetime.fromisoformat(_required_string(raw, "updated_at")),
    )


def _required_string(raw: dict[object, object], field_name: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(raw: dict[object, object], field_name: str) -> str:
    value = raw.get(field_name, "")
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value
