from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DatasetArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
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
    strategy_content_hash: str = Field(min_length=64, max_length=64)
    datasets: tuple[DatasetArtifact, ...]
    configuration: dict[str, Any]
    execution_assumptions: dict[str, Any]
    code_revision: str = Field(min_length=1)
    created_at: datetime
    manifest_hash: str = Field(min_length=64, max_length=64)

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("experiment created_at must be timezone-aware")
        return value

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
        payload = {
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
        return cls(
            **payload,
            datasets=datasets,
            created_at=created_at,
            manifest_hash=_hash(payload),
        )

    def verify(self) -> bool:
        payload = {
            "experiment_id": self.experiment_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_content_hash": self.strategy_content_hash,
            "datasets": [dataset.model_dump(mode="json") for dataset in self.datasets],
            "configuration": self.configuration,
            "execution_assumptions": self.execution_assumptions,
            "code_revision": self.code_revision,
            "created_at": self.created_at.isoformat(),
        }
        return self.manifest_hash == _hash(payload)


class ResearchArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_type: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    experiment_manifest_hash: str = Field(min_length=64, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def belongs_to(self, manifest: ExperimentManifest) -> bool:
        return manifest.verify() and self.experiment_manifest_hash == manifest.manifest_hash


def _hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
