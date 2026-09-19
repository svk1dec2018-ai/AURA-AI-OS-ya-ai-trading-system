from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelArtifactStage(str, Enum):
    RESEARCH = "RESEARCH"
    CHALLENGER = "CHALLENGER"
    SHADOW = "SHADOW"
    DEMO = "DEMO"
    CHAMPION = "CHAMPION"
    RETIRED = "RETIRED"


class ModelArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_key: str = Field(min_length=1)
    version: str = Field(min_length=1)
    stage: ModelArtifactStage
    framework: str = Field(min_length=1)
    task: str = Field(min_length=1)
    markets: tuple[str, ...]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    training_data_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("model artifact created_at must be timezone-aware")
        return value

    @property
    def identity(self) -> str:
        return f"{self.model_key}:{self.version}"


class ModelArtifactStore:
    """Append-only metadata registry; model files themselves stay immutable."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "registry.jsonl"

    def register(self, artifact: ModelArtifact) -> None:
        existing = {item.identity: item for item in self.all()}
        if artifact.identity in existing:
            if existing[artifact.identity] != artifact:
                raise ValueError(f"model artifact collision: {artifact.identity}")
            return
        payload = artifact.model_dump(mode="json")
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self.registry_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def all(self) -> tuple[ModelArtifact, ...]:
        if not self.registry_path.exists():
            return ()
        result = []
        for line in self.registry_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                result.append(ModelArtifact.model_validate_json(line))
        return tuple(result)

    def latest(self, model_key: str, stage: ModelArtifactStage | None = None) -> ModelArtifact | None:
        items = [
            item
            for item in self.all()
            if item.model_key == model_key and (stage is None or item.stage == stage)
        ]
        if not items:
            return None
        items.sort(key=lambda item: (item.created_at, item.version))
        return items[-1]

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def fingerprint_json(payload: object) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()
