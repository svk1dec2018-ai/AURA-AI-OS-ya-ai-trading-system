from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.persistence.wal import JsonlWriteAheadLog, WalEvent
from aura.research.manifest import ExperimentManifest, ResearchArtifact

_REGISTRY_SCHEMA_VERSION = 1
_HEADER_EVENT = "sealed_holdout_registry_initialized"
_PLAN_EVENT = "sealed_holdout_plan_registered"
_RESULT_EVENT = "sealed_holdout_result_recorded"
_HEADER_EVENT_ID = "sealed-holdout-registry:initialized:v1"
_HASH_PATTERN = r"^[0-9a-f]{64}$"

ProtocolValue = str | int | float | bool


class HoldoutError(RuntimeError):
    """A fail-closed sealed-holdout protocol violation."""


class ProtocolParameter(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    value: ProtocolValue

    @field_validator("value", mode="before")
    @classmethod
    def value_must_be_a_finite_scalar(cls, value: object) -> object:
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError("holdout protocol values must be JSON scalars")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("holdout protocol values must be finite")
        return value


class HoldoutMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    value: float

    @field_validator("value", mode="before")
    @classmethod
    def metric_must_be_numeric_and_finite(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("holdout metrics must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("holdout metrics must be finite")
        return value


class SealedHoldoutPlan(BaseModel):
    """Pre-committed strategy, data slice and evaluation protocol.

    The plan binds one immutable strategy experiment to one chronological tail
    slice before its result is recorded. It is research evidence only and carries
    no paper or live deployment authority.
    """

    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(min_length=1)
    manifest: ExperimentManifest
    experiment_manifest_hash: str = Field(pattern=_HASH_PATTERN)
    strategy_content_hash: str = Field(min_length=64, max_length=64)
    dataset_id: str = Field(min_length=1)
    dataset_content_hash: str = Field(min_length=64, max_length=64)
    calibration_end_at: datetime
    holdout_start_at: datetime
    holdout_end_at: datetime
    protocol: tuple[ProtocolParameter, ...]
    protocol_hash: str = Field(pattern=_HASH_PATTERN)
    declared_at: datetime
    seal_hash: str = Field(pattern=_HASH_PATTERN)

    @field_validator(
        "calibration_end_at",
        "holdout_start_at",
        "holdout_end_at",
        "declared_at",
    )
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("holdout timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_plan(self) -> SealedHoldoutPlan:
        if not self.manifest.verify():
            raise ValueError("holdout contains an invalid experiment manifest")
        if self.experiment_manifest_hash != self.manifest.manifest_hash:
            raise ValueError("holdout experiment manifest hash mismatch")
        if self.strategy_content_hash != self.manifest.strategy_content_hash:
            raise ValueError("holdout strategy hash does not match its manifest")
        datasets = [item for item in self.manifest.datasets if item.dataset_id == self.dataset_id]
        if len(datasets) != 1 or datasets[0].content_hash != self.dataset_content_hash:
            raise ValueError("holdout dataset does not match its manifest")
        dataset = datasets[0]
        if not self.calibration_end_at <= self.holdout_start_at < self.holdout_end_at:
            raise ValueError("holdout must be a chronological tail after calibration")
        if not (
            dataset.start_at < self.calibration_end_at and self.holdout_end_at == dataset.end_at
        ):
            raise ValueError("holdout boundaries must form the manifest dataset tail")
        if self.declared_at < self.manifest.created_at:
            raise ValueError("holdout plan cannot predate its experiment manifest")
        names = tuple(item.name for item in self.protocol)
        if not names:
            raise ValueError("holdout evaluation protocol cannot be empty")
        if names != tuple(sorted(names)) or len(set(names)) != len(names):
            raise ValueError("holdout protocol parameters must be unique and sorted")
        if self.protocol_hash != _hash(_protocol_payload(self.protocol)):
            raise ValueError("holdout protocol hash mismatch")
        if self.seal_hash != _hash(_plan_payload(self)):
            raise ValueError("holdout plan seal hash mismatch")
        return self

    @classmethod
    def build(
        cls,
        *,
        plan_id: str,
        manifest: ExperimentManifest,
        dataset_id: str,
        calibration_end_at: datetime,
        holdout_start_at: datetime,
        holdout_end_at: datetime,
        evaluation_protocol: Mapping[str, ProtocolValue],
        declared_at: datetime,
    ) -> SealedHoldoutPlan:
        if not manifest.verify():
            raise HoldoutError("cannot seal a holdout against an invalid experiment manifest")
        for name, value in (
            ("calibration_end_at", calibration_end_at),
            ("holdout_start_at", holdout_start_at),
            ("holdout_end_at", holdout_end_at),
            ("declared_at", declared_at),
        ):
            _require_aware(value, name)
        if declared_at < manifest.created_at:
            raise HoldoutError("holdout plan cannot predate its experiment manifest")
        datasets = [item for item in manifest.datasets if item.dataset_id == dataset_id]
        if len(datasets) != 1:
            raise HoldoutError("holdout dataset_id must identify exactly one manifest dataset")
        dataset = datasets[0]
        if not (
            dataset.start_at
            < calibration_end_at
            <= holdout_start_at
            < holdout_end_at
            == dataset.end_at
        ):
            raise HoldoutError("holdout boundaries must form the manifest dataset tail")

        protocol = tuple(
            ProtocolParameter(name=name, value=value)
            for name, value in sorted(evaluation_protocol.items())
        )
        protocol_hash = _hash(_protocol_payload(protocol))
        plan_payload = {
            "plan_id": plan_id,
            "manifest": manifest.model_dump(mode="json"),
            "experiment_manifest_hash": manifest.manifest_hash,
            "strategy_content_hash": manifest.strategy_content_hash,
            "dataset_id": dataset.dataset_id,
            "dataset_content_hash": dataset.content_hash,
            "calibration_end_at": calibration_end_at.isoformat(),
            "holdout_start_at": holdout_start_at.isoformat(),
            "holdout_end_at": holdout_end_at.isoformat(),
            "protocol": _protocol_payload(protocol),
            "protocol_hash": protocol_hash,
            "declared_at": declared_at.isoformat(),
        }
        return cls(
            plan_id=plan_id,
            manifest=manifest,
            experiment_manifest_hash=manifest.manifest_hash,
            strategy_content_hash=manifest.strategy_content_hash,
            dataset_id=dataset.dataset_id,
            dataset_content_hash=dataset.content_hash,
            calibration_end_at=calibration_end_at,
            holdout_start_at=holdout_start_at,
            holdout_end_at=holdout_end_at,
            protocol=protocol,
            protocol_hash=protocol_hash,
            declared_at=declared_at,
            seal_hash=_hash(plan_payload),
        )

    def verify(self) -> bool:
        try:
            datasets = [
                item for item in self.manifest.datasets if item.dataset_id == self.dataset_id
            ]
            names = tuple(item.name for item in self.protocol)
            return (
                self.manifest.verify()
                and self.experiment_manifest_hash == self.manifest.manifest_hash
                and self.strategy_content_hash == self.manifest.strategy_content_hash
                and len(datasets) == 1
                and datasets[0].content_hash == self.dataset_content_hash
                and datasets[0].start_at
                < self.calibration_end_at
                <= self.holdout_start_at
                < self.holdout_end_at
                == datasets[0].end_at
                and self.declared_at >= self.manifest.created_at
                and bool(names)
                and names == tuple(sorted(names))
                and len(set(names)) == len(names)
                and self.protocol_hash == _hash(_protocol_payload(self.protocol))
                and self.seal_hash == _hash(_plan_payload(self))
            )
        except (AttributeError, TypeError, ValueError):
            return False


class SealedHoldoutResult(BaseModel):
    """Measured output from the single permitted exposure of a sealed slice."""

    model_config = ConfigDict(frozen=True)

    seal_hash: str = Field(pattern=_HASH_PATTERN)
    experiment_manifest_hash: str = Field(pattern=_HASH_PATTERN)
    strategy_content_hash: str = Field(min_length=64, max_length=64)
    artifact_hash: str = Field(min_length=64, max_length=64)
    observations: int = Field(gt=0)
    metrics: tuple[HoldoutMetric, ...]
    evaluated_at: datetime
    result_hash: str = Field(pattern=_HASH_PATTERN)

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("holdout evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_result(self) -> SealedHoldoutResult:
        names = tuple(item.name for item in self.metrics)
        if not names:
            raise ValueError("holdout result requires at least one metric")
        if names != tuple(sorted(names)) or len(set(names)) != len(names):
            raise ValueError("holdout metrics must be unique and sorted")
        if self.result_hash != _hash(_result_payload(self)):
            raise ValueError("holdout result hash mismatch")
        return self

    @classmethod
    def build(
        cls,
        plan: SealedHoldoutPlan,
        *,
        artifact_hash: str,
        observations: int,
        metrics: Mapping[str, int | float],
        evaluated_at: datetime,
    ) -> SealedHoldoutResult:
        if not plan.verify():
            raise HoldoutError("cannot record a result for an invalid holdout plan")
        _require_aware(evaluated_at, "evaluated_at")
        metric_items = tuple(
            HoldoutMetric(name=name, value=value) for name, value in sorted(metrics.items())
        )
        result_payload = {
            "seal_hash": plan.seal_hash,
            "experiment_manifest_hash": plan.experiment_manifest_hash,
            "strategy_content_hash": plan.strategy_content_hash,
            "artifact_hash": artifact_hash,
            "observations": observations,
            "metrics": [item.model_dump(mode="json") for item in metric_items],
            "evaluated_at": evaluated_at.isoformat(),
        }
        return cls(
            seal_hash=plan.seal_hash,
            experiment_manifest_hash=plan.experiment_manifest_hash,
            strategy_content_hash=plan.strategy_content_hash,
            artifact_hash=artifact_hash,
            observations=observations,
            metrics=metric_items,
            evaluated_at=evaluated_at,
            result_hash=_hash(result_payload),
        )

    def verify(self, plan: SealedHoldoutPlan) -> bool:
        try:
            names = tuple(item.name for item in self.metrics)
            return (
                plan.verify()
                and self.seal_hash == plan.seal_hash
                and self.experiment_manifest_hash == plan.experiment_manifest_hash
                and self.strategy_content_hash == plan.strategy_content_hash
                and len(self.artifact_hash) == 64
                and self.observations > 0
                and bool(names)
                and names == tuple(sorted(names))
                and len(set(names)) == len(names)
                and all(math.isfinite(item.value) for item in self.metrics)
                and self.evaluated_at.tzinfo is not None
                and self.evaluated_at.utcoffset() is not None
                and self.evaluated_at >= plan.declared_at
                and self.result_hash == _hash(_result_payload(self))
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def to_research_artifact(self) -> ResearchArtifact:
        return ResearchArtifact(
            artifact_type="sealed_holdout",
            content_hash=self.result_hash,
            experiment_manifest_hash=self.experiment_manifest_hash,
            metadata={
                "seal_hash": self.seal_hash,
                "source_artifact_hash": self.artifact_hash,
                "observations": self.observations,
                "metrics": {item.name: item.value for item in self.metrics},
                "evaluated_at": self.evaluated_at.isoformat(),
                "historical_research_only": True,
                "paper_validated": False,
                "live_approved": False,
                "live_money_enabled": False,
            },
        )


class SealedHoldoutRegistry:
    """Durable one-use ledger for chronological research holdouts.

    A dataset tail can be claimed by only one plan in a registry. Result retries
    are idempotent only when byte-for-byte equivalent; a different second result
    is rejected. WAL corruption or semantically invalid replay stops recovery.
    """

    def __init__(self, journal_path: Path) -> None:
        self.journal_path = journal_path
        self.recovered_events = 0
        self._plans_by_id: dict[str, SealedHoldoutPlan] = {}
        self._plans_by_hash: dict[str, SealedHoldoutPlan] = {}
        self._slice_claims: dict[str, str] = {}
        self._results: dict[str, SealedHoldoutResult] = {}
        self._wal = JsonlWriteAheadLog(journal_path)
        self._initialize_or_replay()

    def seal(self, plan: SealedHoldoutPlan) -> bool:
        if plan.declared_at > datetime.now(UTC):
            raise HoldoutError("holdout declaration cannot be in the future")
        self._validate_new_plan(plan)
        existing = self._plans_by_id.get(plan.plan_id)
        if existing == plan:
            return False
        event = self._wal.append(
            event_type=_PLAN_EVENT,
            payload={
                "registry_schema_version": _REGISTRY_SCHEMA_VERSION,
                "plan": plan.model_dump(mode="json"),
            },
            correlation_id=plan.plan_id,
            event_id=_plan_event_id(plan),
        )
        self._apply_plan_event(event)
        return True

    def record_result(self, result: SealedHoldoutResult) -> bool:
        if result.evaluated_at > datetime.now(UTC):
            raise HoldoutError("holdout evaluation cannot be in the future")
        plan = self._plans_by_hash.get(result.seal_hash)
        if plan is None:
            raise HoldoutError("holdout result has no registered sealed plan")
        existing = self._results.get(result.seal_hash)
        if existing is not None:
            if existing == result:
                return False
            raise HoldoutError("sealed holdout slice has already been consumed")
        if not result.verify(plan):
            raise HoldoutError("holdout result does not match its sealed plan")
        event = self._wal.append(
            event_type=_RESULT_EVENT,
            payload={
                "registry_schema_version": _REGISTRY_SCHEMA_VERSION,
                "result": result.model_dump(mode="json"),
            },
            correlation_id=plan.plan_id,
            event_id=_result_event_id(result),
        )
        self._apply_result_event(event)
        return True

    def get_plan(self, plan_id: str) -> SealedHoldoutPlan:
        try:
            return self._plans_by_id[plan_id]
        except KeyError as exc:
            raise KeyError(f"unknown sealed holdout plan: {plan_id}") from exc

    def get_result(self, seal_hash: str) -> SealedHoldoutResult:
        try:
            return self._results[seal_hash]
        except KeyError as exc:
            raise KeyError(f"unconsumed sealed holdout: {seal_hash}") from exc

    def is_consumed(self, seal_hash: str) -> bool:
        return seal_hash in self._results

    def _initialize_or_replay(self) -> None:
        events = self._wal.read_all()
        if not events:
            self._wal.append(
                event_type=_HEADER_EVENT,
                payload={"registry_schema_version": _REGISTRY_SCHEMA_VERSION},
                correlation_id="sealed-holdout-registry",
                event_id=_HEADER_EVENT_ID,
            )
            return
        header = events[0]
        self._validate_event_schema(header)
        if (
            header.event_type != _HEADER_EVENT
            or header.event_id != _HEADER_EVENT_ID
            or header.correlation_id != "sealed-holdout-registry"
        ):
            raise HoldoutError("sealed holdout journal is missing its header")
        for event in events[1:]:
            self._validate_event_schema(event)
            if event.event_type == _PLAN_EVENT:
                self._apply_plan_event(event)
            elif event.event_type == _RESULT_EVENT:
                self._apply_result_event(event)
            else:
                raise HoldoutError(f"unknown sealed holdout event: {event.event_type}")
            self.recovered_events += 1

    def _validate_new_plan(self, plan: SealedHoldoutPlan) -> None:
        if not plan.verify():
            raise HoldoutError("invalid sealed holdout plan")
        existing = self._plans_by_id.get(plan.plan_id)
        if existing is not None and existing != plan:
            raise HoldoutError("holdout plan_id cannot be rebound")
        existing_hash = self._plans_by_hash.get(plan.seal_hash)
        if existing_hash is not None and existing_hash != plan:
            raise HoldoutError("holdout seal hash collision")
        claimed_by = self._slice_claims.get(_slice_key(plan))
        if claimed_by is not None and claimed_by != plan.seal_hash:
            raise HoldoutError("chronological holdout slice is already claimed")

    def _apply_plan_event(self, event: WalEvent) -> None:
        try:
            plan = SealedHoldoutPlan.model_validate(event.payload["plan"])
        except Exception as exc:
            raise HoldoutError(f"invalid holdout plan event: {event.event_id}") from exc
        if event.event_id != _plan_event_id(plan):
            raise HoldoutError(f"holdout plan event_id mismatch: {event.event_id}")
        if event.correlation_id != plan.plan_id:
            raise HoldoutError(f"holdout plan correlation mismatch: {event.event_id}")
        if plan.declared_at > event.created_at:
            raise HoldoutError(f"holdout declaration postdates its event: {event.event_id}")
        self._validate_new_plan(plan)
        if plan.plan_id in self._plans_by_id:
            raise HoldoutError(f"duplicate holdout plan event: {event.event_id}")
        self._plans_by_id[plan.plan_id] = plan
        self._plans_by_hash[plan.seal_hash] = plan
        self._slice_claims[_slice_key(plan)] = plan.seal_hash

    def _apply_result_event(self, event: WalEvent) -> None:
        try:
            result = SealedHoldoutResult.model_validate(event.payload["result"])
        except Exception as exc:
            raise HoldoutError(f"invalid holdout result event: {event.event_id}") from exc
        plan = self._plans_by_hash.get(result.seal_hash)
        if plan is None:
            raise HoldoutError(f"holdout result precedes its plan: {event.event_id}")
        if event.event_id != _result_event_id(result):
            raise HoldoutError(f"holdout result event_id mismatch: {event.event_id}")
        if event.correlation_id != plan.plan_id:
            raise HoldoutError(f"holdout result correlation mismatch: {event.event_id}")
        if result.evaluated_at > event.created_at:
            raise HoldoutError(f"holdout evaluation postdates its event: {event.event_id}")
        if result.seal_hash in self._results:
            raise HoldoutError(f"duplicate holdout result event: {event.event_id}")
        if not result.verify(plan):
            raise HoldoutError(f"holdout result violates its seal: {event.event_id}")
        self._results[result.seal_hash] = result

    @staticmethod
    def _validate_event_schema(event: WalEvent) -> None:
        if event.schema_version != 1:
            raise HoldoutError(f"unsupported WAL schema in event {event.event_id}")
        if event.created_at.tzinfo is None or event.created_at.utcoffset() is None:
            raise HoldoutError(f"naive event timestamp in event {event.event_id}")
        schema_version = event.payload.get("registry_schema_version")
        if type(schema_version) is not int or schema_version != _REGISTRY_SCHEMA_VERSION:
            raise HoldoutError(f"unsupported holdout schema in event {event.event_id}")


def _plan_event_id(plan: SealedHoldoutPlan) -> str:
    return f"sealed-holdout-plan:{plan.seal_hash}"


def _result_event_id(result: SealedHoldoutResult) -> str:
    return f"sealed-holdout-result:{result.seal_hash}"


def _slice_key(plan: SealedHoldoutPlan) -> str:
    return _hash(
        {
            "dataset_content_hash": plan.dataset_content_hash,
            "holdout_start_at": plan.holdout_start_at.isoformat(),
            "holdout_end_at": plan.holdout_end_at.isoformat(),
        }
    )


def _protocol_payload(
    protocol: tuple[ProtocolParameter, ...],
) -> list[dict[str, ProtocolValue]]:
    return [item.model_dump(mode="json") for item in protocol]


def _plan_payload(plan: SealedHoldoutPlan) -> dict[str, object]:
    return {
        "plan_id": plan.plan_id,
        "manifest": plan.manifest.model_dump(mode="json"),
        "experiment_manifest_hash": plan.experiment_manifest_hash,
        "strategy_content_hash": plan.strategy_content_hash,
        "dataset_id": plan.dataset_id,
        "dataset_content_hash": plan.dataset_content_hash,
        "calibration_end_at": plan.calibration_end_at.isoformat(),
        "holdout_start_at": plan.holdout_start_at.isoformat(),
        "holdout_end_at": plan.holdout_end_at.isoformat(),
        "protocol": _protocol_payload(plan.protocol),
        "protocol_hash": plan.protocol_hash,
        "declared_at": plan.declared_at.isoformat(),
    }


def _result_payload(result: SealedHoldoutResult) -> dict[str, object]:
    return {
        "seal_hash": result.seal_hash,
        "experiment_manifest_hash": result.experiment_manifest_hash,
        "strategy_content_hash": result.strategy_content_hash,
        "artifact_hash": result.artifact_hash,
        "observations": result.observations,
        "metrics": [item.model_dump(mode="json") for item in result.metrics],
        "evaluated_at": result.evaluated_at.isoformat(),
    }


def _hash(payload: object) -> str:
    canonical = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
