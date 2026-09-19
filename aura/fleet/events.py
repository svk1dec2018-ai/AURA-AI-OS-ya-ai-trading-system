from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FleetEventKind(str, Enum):
    MARKET_TICK = "market.tick"
    MARKET_CANDLE = "market.candle"
    FEATURE_VECTOR = "features.vector"
    ML_VOTE = "ml.vote"
    AGENT_VERDICT = "agents.verdict"
    NEWS_SIGNAL = "news.signal"
    RISK_DECISION = "risk.decision"
    EXECUTION_ORDER = "execution.order"
    EXECUTION_FILL = "execution.fill"
    RESEARCH_EVENT = "research.event"
    SYSTEM_HEALTH = "system.health"


class FleetEvent(BaseModel):
    """Versioned event envelope shared by AURA fleet services."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=160)
    kind: FleetEventKind
    source: str = Field(min_length=1, max_length=120)
    symbol: str | None = Field(default=None, max_length=120)
    venue: str | None = Field(default=None, max_length=120)
    correlation_id: str | None = Field(default=None, max_length=200)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = Field(default=1, ge=1, le=100)

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fleet event timestamp must be timezone-aware")
        return value
