from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PrimeEventKind(str, Enum):
    MARKET = "market"
    FEATURE = "feature"
    MODEL = "model"
    AGENT = "agent"
    RISK = "risk"
    ORDER = "order"
    FILL = "fill"
    PORTFOLIO = "portfolio"
    INTELLIGENCE = "intelligence"
    RESEARCH = "research"
    SYSTEM = "system"


class ReadinessState(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    OFFLINE = "OFFLINE"


class PrimeEvent(BaseModel):
    """Canonical replayable event envelope for AURA Prime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=100)
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=160)
    correlation_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=160)
    causation_id: str | None = Field(default=None, max_length=160)
    kind: PrimeEventKind
    source: str = Field(min_length=1, max_length=120)
    market: str | None = Field(default=None, max_length=80)
    symbol: str | None = Field(default=None, max_length=120)
    observed_at: datetime
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)
    point_in_time_safe: bool = True
    execution_authority: bool = False

    @field_validator("observed_at", "received_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("PrimeEvent timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_temporal_semantics(self) -> PrimeEvent:
        if not self.point_in_time_safe:
            raise ValueError("non-point-in-time-safe PrimeEvent is forbidden")
        if self.observed_at > self.received_at:
            raise ValueError("PrimeEvent cannot be received before observation")
        if self.execution_authority and self.kind not in {
            PrimeEventKind.RISK,
            PrimeEventKind.ORDER,
            PrimeEventKind.FILL,
        }:
            raise ValueError("financial authority is restricted to risk/order/fill events")
        return self
