from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DatasetArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    start_at: datetime
    end_at: datetime
    point_in_time_safe: bool = True

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("dataset timestamps must be timezone-aware")
        return value

    @field_validator("symbols", "timeframes")
    @classmethod
    def dimensions_must_be_unique_and_normalized(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("dataset dimensions must contain non-empty normalized values")
        if len(set(value)) != len(value):
            raise ValueError("dataset dimensions must not contain duplicates")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_dataset(self) -> DatasetArtifact:
        if self.end_at <= self.start_at:
            raise ValueError("dataset end_at must be after start_at")
        if not self.symbols or not self.timeframes:
            raise ValueError("dataset must declare symbols and timeframes")
        if not self.point_in_time_safe:
            raise ValueError("non-point-in-time-safe dataset cannot enter research manifest")
        return self


class ExperimentManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    strategy_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    datasets: tuple[DatasetArtifact, ...]
    configuration: dict[str, Any]
    execution_assumptions: dict[str, Any]
    code_revision: str = Field(min_length=1)
    created_at: datetime
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("experiment created_at must be timezone-aware")
        return value

    @field_validator("configuration", "execution_assumptions")
    @classmethod
    def mappings_must_be_canonical_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_value(value)
        return value

    @model_validator(mode="after")
    def datasets_must_be_unique(self) -> ExperimentManifest:
        dataset_ids = [dataset.dataset_id for dataset in self.datasets]
        if not dataset_ids:
            raise ValueError("experiment requires at least one dataset")
        if len(set(dataset_ids)) != len(dataset_ids):
            raise ValueError("experiment dataset IDs must be unique")
        return self

    @classmethod
    def build(
        cls,
        *,
        experiment_id: str,
        strategy_id: str,
        strategy_version: str,
        strategy_content_hash: str,
        datasets: tuple[DatasetArtifact, ...],
        configuration: dict[str, Any],
        execution_assumptions: dict[str, Any],
        code_revision: str,
        created_at: datetime,
    ) -> ExperimentManifest:
        if not datasets:
            raise ValueError("experiment requires at least one dataset")
        _validate_json_value(configuration)
        _validate_json_value(execution_assumptions)
        payload = _payload(
            experiment_id=experiment_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            strategy_content_hash=strategy_content_hash,
            datasets=tuple(sorted(datasets, key=lambda dataset: dataset.dataset_id)),
            configuration=configuration,
            execution_assumptions=execution_assumptions,
            code_revision=code_revision,
            created_at=created_at,
        )
        return cls(
            experiment_id=experiment_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            strategy_content_hash=strategy_content_hash,
            datasets=tuple(sorted(datasets, key=lambda dataset: dataset.dataset_id)),
            configuration=dict(configuration),
            execution_assumptions=dict(execution_assumptions),
            code_revision=code_revision,
            created_at=created_at,
            manifest_hash=_hash(payload),
        )

    def verify(self) -> bool:
        return self.manifest_hash == _hash(
            _payload(
                experiment_id=self.experiment_id,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                strategy_content_hash=self.strategy_content_hash,
                datasets=self.datasets,
                configuration=self.configuration,
                execution_assumptions=self.execution_assumptions,
                code_revision=self.code_revision,
                created_at=self.created_at,
            )
        )


class ResearchArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_type: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_canonical_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_value(value)
        return value

    def belongs_to(self, manifest: ExperimentManifest) -> bool:
        return manifest.verify() and self.experiment_manifest_hash == manifest.manifest_hash


def _payload(
    *,
    experiment_id: str,
    strategy_id: str,
    strategy_version: str,
    strategy_content_hash: str,
    datasets: tuple[DatasetArtifact, ...],
    configuration: dict[str, Any],
    execution_assumptions: dict[str, Any],
    code_revision: str,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "strategy_content_hash": strategy_content_hash,
        "datasets": [dataset.model_dump(mode="json") for dataset in datasets],
        "configuration": configuration,
        "execution_assumptions": execution_assumptions,
        "code_revision": code_revision,
        "created_at": created_at.isoformat(),
    }


def _hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_json_value(value: Any, *, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or Infinity")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} must use string object keys")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise TypeError(f"{path} contains non-JSON value of type {type(value).__name__}")
