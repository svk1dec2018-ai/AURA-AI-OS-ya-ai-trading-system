from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.research.autonomy import ResearchHypothesis


class HypothesisRequest(BaseModel):
    """Canonical, provenance-bound input for a research hypothesis.

    The request is data only. It cannot carry executable code, broker authority,
    risk settings, or a request to promote a strategy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    thesis: str = Field(min_length=1, max_length=2_000)
    market_scope: tuple[str, ...] = Field(min_length=1)
    timeframe_scope: tuple[str, ...] = Field(min_length=1)
    provenance: str = Field(min_length=1, max_length=500)
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    parent_strategy_id: str | None = Field(default=None, min_length=1)

    @field_validator("thesis", "provenance")
    @classmethod
    def text_must_be_normalized(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("research text cannot be blank")
        return normalized

    @field_validator("market_scope", "timeframe_scope")
    @classmethod
    def scope_must_be_normalized(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(item.strip() for item in value))
        if any(not item for item in normalized):
            raise ValueError("research scope cannot contain blank values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("research scope cannot contain duplicates")
        return normalized

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class DeterministicHypothesisGenerator:
    """Build reproducible hypotheses without granting deployment authority."""

    def generate(self, request: HypothesisRequest) -> ResearchHypothesis:
        payload = request.model_dump(mode="json", exclude={"created_at"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return ResearchHypothesis(
            hypothesis_id=f"hyp-{digest[:20]}",
            thesis=request.thesis,
            market_scope=request.market_scope,
            timeframe_scope=request.timeframe_scope,
            parent_strategy_id=request.parent_strategy_id,
            created_at=request.created_at,
        )
