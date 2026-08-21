from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.domain.models import NormalizedCandle, SignalIntent


class AgentRole(str, Enum):
    HTF_BIAS = "htf_bias"
    SMC_ICT = "smc_ict"
    TECHNICAL = "technical"
    VOLUME_VWAP = "volume_vwap"
    FORECAST = "forecast"
    OPTIONS_VOLATILITY = "options_volatility"
    MACRO_SENTIMENT = "macro_sentiment"
    CROSS_MARKET = "cross_market"
    REGIME = "regime"
    EXECUTION_QUALITY = "execution_quality"


class EvidenceSourceType(str, Enum):
    MARKET_DATA = "market_data"
    DERIVATIVES = "derivatives"
    MACRO = "macro"
    NEWS = "news"
    RESEARCH = "research"
    INTERNAL_MEMORY = "internal_memory"


class EvidenceSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    source_type: EvidenceSourceType
    observed_at: datetime
    trust_score: float = Field(ge=0.0, le=1.0)
    point_in_time_safe: bool = True

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        return value


class AgentContext(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    correlation_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    decision_timeframe: str = Field(min_length=1)
    candles: tuple[NormalizedCandle, ...]
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("candles")
    @classmethod
    def candles_must_be_closed_and_consistent(
        cls,
        candles: tuple[NormalizedCandle, ...],
    ) -> tuple[NormalizedCandle, ...]:
        if not candles:
            raise ValueError("agent context requires at least one candle")
        if any(not candle.closed for candle in candles):
            raise ValueError("multi-agent decisions may use only closed candles")
        symbols = {candle.symbol for candle in candles}
        if len(symbols) != 1:
            raise ValueError("agent context candles must refer to one canonical symbol")
        timeframes = {candle.timeframe for candle in candles}
        if len(timeframes) != 1:
            raise ValueError("agent context candle series must use one decision timeframe")
        return candles

    @model_validator(mode="after")
    def validate_point_in_time_context(self) -> AgentContext:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("agent context created_at must be timezone-aware")
        if any(candle.symbol != self.symbol for candle in self.candles):
            raise ValueError("agent context symbol does not match candle symbol")
        if any(candle.timeframe != self.decision_timeframe for candle in self.candles):
            raise ValueError("agent decision_timeframe does not match candle timeframe")
        if any(candle.close_time > self.created_at for candle in self.candles):
            raise ValueError("agent context contains candle data from the future")
        return self


class AgentEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(min_length=1)
    role: AgentRole
    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    thesis: str = Field(min_length=1)
    risk_flags: tuple[str, ...] = ()
    sources: tuple[EvidenceSource, ...]
    features: dict[str, Any] = Field(default_factory=dict)
    execution_authority: Literal[False] = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("sources")
    @classmethod
    def require_evidence_sources(
        cls,
        sources: tuple[EvidenceSource, ...],
    ) -> tuple[EvidenceSource, ...]:
        if not sources:
            raise ValueError("specialist evidence must cite at least one source")
        if any(not source.point_in_time_safe for source in sources):
            raise ValueError("non-point-in-time-safe evidence is forbidden in decisions")
        return sources

    @model_validator(mode="after")
    def sources_cannot_arrive_after_generation(self) -> AgentEvidence:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("agent evidence generated_at must be timezone-aware")
        if any(source.observed_at > self.generated_at for source in self.sources):
            raise ValueError("agent evidence cites a source observed after the decision evidence")
        return self


class AgentFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    role: AgentRole
    error_type: str
    message: str


class AgentRound(BaseModel):
    model_config = ConfigDict(frozen=True)

    correlation_id: str
    evidence: tuple[AgentEvidence, ...]
    failures: tuple[AgentFailure, ...] = ()
    started_at: datetime
    completed_at: datetime


class DecisionReasonCode(str, Enum):
    QUORUM_NOT_MET = "quorum_not_met"
    NO_DIRECTIONAL_EVIDENCE = "no_directional_evidence"
    DIRECTIONAL_DISAGREEMENT = "directional_disagreement"
    WEIGHTED_EVIDENCE = "weighted_evidence"


class EvidenceContribution(BaseModel):
    """One specialist's deterministic contribution to CEO evidence fusion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(min_length=1)
    role: AgentRole
    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    thesis: str = Field(min_length=1)
    source_trust: float = Field(ge=0.0, le=1.0)
    role_weight: float = Field(gt=0.0)
    reliability_weight: float = Field(gt=0.0)
    effective_score: float = Field(ge=0.0)
    source_ids: tuple[str, ...]
    risk_flags: tuple[str, ...] = ()


class CEODecisionTrace(BaseModel):
    """Machine-readable, replayable explanation for one advisory CEO decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    correlation_id: str = Field(min_length=1)
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    market: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    evidence_count: int = Field(ge=0)
    distinct_role_count: int = Field(ge=0)
    failure_agents: tuple[str, ...]
    min_agents: int = Field(gt=0)
    min_distinct_roles: int = Field(gt=0)
    min_directional_margin: float = Field(ge=0.0, le=1.0)
    long_score: float = Field(ge=0.0)
    short_score: float = Field(ge=0.0)
    directional_margin: float = Field(ge=0.0, le=1.0)
    reason_code: DecisionReasonCode
    contributions: tuple[EvidenceContribution, ...]
    execution_authority: Literal[False] = False


class CEODecisionMemo(BaseModel):
    """Advisory multi-agent synthesis; never an executable order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str
    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_agents: tuple[str, ...]
    opposing_agents: tuple[str, ...]
    abstaining_agents: tuple[str, ...]
    risk_flags: tuple[str, ...]
    rationale: str
    quorum_met: bool
    decision_trace: CEODecisionTrace | None = None
    execution_authority: Literal[False] = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
