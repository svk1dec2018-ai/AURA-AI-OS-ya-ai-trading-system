from __future__ import annotations

import importlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aura.domain.models import SignalIntent

from .ensemble import ModelVote


class LinearProbabilityArtifact(BaseModel):
    """Portable dependency-light logistic model for live Prime inference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    model_key: str = Field(min_length=1)
    version: str = Field(min_length=1)
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    long_threshold: float = Field(default=0.58, gt=0.5, lt=1.0)
    short_threshold: float = Field(default=0.42, gt=0.0, lt=0.5)
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    calibration: float = Field(default=0.5, ge=0.0, le=1.0)
    training_data_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def dimensions_match(self) -> LinearProbabilityArtifact:
        if not self.feature_names:
            raise ValueError("linear model requires features")
        if len(self.feature_names) != len(self.coefficients):
            raise ValueError("linear model feature/weight dimensions do not match")
        if self.short_threshold >= self.long_threshold:
            raise ValueError("short threshold must be below long threshold")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("linear model created_at must be timezone-aware")
        return self

    def probability(self, features: dict[str, float]) -> float:
        missing = [name for name in self.feature_names if name not in features]
        if missing:
            raise ValueError("model features missing: " + ", ".join(missing))
        score = self.intercept + sum(
            coefficient * float(features[name])
            for name, coefficient in zip(
                self.feature_names,
                self.coefficients,
                strict=True,
            )
        )
        if score >= 0:
            exp_value = math.exp(-score)
            return 1.0 / (1.0 + exp_value)
        exp_value = math.exp(score)
        return exp_value / (1.0 + exp_value)

    def vote(self, features: dict[str, float]) -> ModelVote:
        probability = self.probability(features)
        if probability >= self.long_threshold:
            intent = SignalIntent.LONG
            confidence = probability
        elif probability <= self.short_threshold:
            intent = SignalIntent.SHORT
            confidence = 1.0 - probability
        else:
            intent = SignalIntent.FLAT
            confidence = 1.0 - abs(probability - 0.5) * 2.0
        return ModelVote(
            model_key=f"{self.model_key}:{self.version}",
            intent=intent,
            confidence=min(1.0, max(0.0, confidence)),
            reliability=self.reliability,
            calibration=self.calibration,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> LinearProbabilityArtifact:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class SklearnLogisticTrainer:
    """Offline/research trainer. Live inference uses LinearProbabilityArtifact only."""

    def fit(
        self,
        rows: list[dict[str, float]],
        labels: list[int],
        *,
        model_key: str,
        version: str,
        training_data_fingerprint: str,
        reliability: float = 0.5,
        calibration: float = 0.5,
    ) -> LinearProbabilityArtifact:
        if len(rows) != len(labels) or len(rows) < 20:
            raise ValueError("trainer requires matching rows/labels and at least 20 samples")
        feature_names = tuple(sorted(rows[0]))
        if not feature_names:
            raise ValueError("training rows must contain features")
        if any(tuple(sorted(row)) != feature_names for row in rows):
            raise ValueError("all training rows must use one feature schema")
        if set(labels) - {0, 1}:
            raise ValueError("labels must be binary 0/1")

        linear_model = importlib.import_module("sklearn.linear_model")
        estimator = linear_model.LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=0,
        )
        matrix = [[float(row[name]) for name in feature_names] for row in rows]
        estimator.fit(matrix, labels)
        coefficients = tuple(float(value) for value in estimator.coef_[0])
        intercept = float(estimator.intercept_[0])
        return LinearProbabilityArtifact(
            model_key=model_key,
            version=version,
            feature_names=feature_names,
            coefficients=coefficients,
            intercept=intercept,
            reliability=reliability,
            calibration=calibration,
            training_data_fingerprint=training_data_fingerprint,
        )


def load_training_rows(path: Path) -> tuple[list[dict[str, float]], list[int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("training payload must be a list")
    rows: list[dict[str, float]] = []
    labels: list[int] = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("features"), dict):
            raise ValueError("training item requires features object")
        rows.append({str(k): float(v) for k, v in item["features"].items()})
        labels.append(int(item["label"]))
    return rows, labels
