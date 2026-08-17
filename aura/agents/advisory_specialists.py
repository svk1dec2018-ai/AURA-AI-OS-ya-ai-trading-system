from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.domain.models import SignalIntent


class ExecutionQualitySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    observed_at: datetime
    spread_bps: float = Field(ge=0.0)
    estimated_slippage_bps: float = Field(ge=0.0)
    top_of_book_notional: float = Field(ge=0.0)
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution snapshot observed_at must be timezone-aware")
        return value


class ExecutionQualitySpecialist(SpecialistAgent):
    agent_id = "deterministic:execution_quality:v1"
    role = AgentRole.EXECUTION_QUALITY

    def __init__(
        self,
        *,
        max_spread_bps: float = 20.0,
        max_slippage_bps: float = 20.0,
        min_top_of_book_notional: float = 1000.0,
    ) -> None:
        if max_spread_bps < 0 or max_slippage_bps < 0 or min_top_of_book_notional < 0:
            raise ValueError("execution-quality thresholds cannot be negative")
        self.max_spread_bps = max_spread_bps
        self.max_slippage_bps = max_slippage_bps
        self.min_top_of_book_notional = min_top_of_book_notional

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        raw = context.metadata.get("execution_quality")
        if raw is None:
            return self._abstain(context, "execution-quality snapshot is missing", "execution_quality_missing")
        snapshot = ExecutionQualitySnapshot.model_validate(raw)
        if snapshot.observed_at > context.created_at:
            return self._abstain(context, "execution-quality snapshot is from the future", "execution_quality_future")

        flags: list[str] = []
        if snapshot.spread_bps > self.max_spread_bps:
            flags.append("spread_too_wide")
        if snapshot.estimated_slippage_bps > self.max_slippage_bps:
            flags.append("estimated_slippage_too_high")
        if snapshot.top_of_book_notional < self.min_top_of_book_notional:
            flags.append("top_of_book_liquidity_too_low")

        severity = max(
            snapshot.spread_bps / max(self.max_spread_bps, 1e-12),
            snapshot.estimated_slippage_bps / max(self.max_slippage_bps, 1e-12),
            (
                self.min_top_of_book_notional / max(snapshot.top_of_book_notional, 1e-12)
                if self.min_top_of_book_notional > 0
                else 0.0
            ),
        )
        confidence = min(abs(severity - 1.0), 1.0) if flags else min(1.0 / max(severity, 1.0), 1.0)
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=SignalIntent.FLAT,
            confidence=confidence,
            thesis=(
                f"execution advisory: spread={snapshot.spread_bps:.2f}bps, "
                f"slippage={snapshot.estimated_slippage_bps:.2f}bps, "
                f"top-book={snapshot.top_of_book_notional:.2f}"
            ),
            risk_flags=tuple(sorted(flags)),
            sources=(
                EvidenceSource(
                    source_id=snapshot.source_id,
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=snapshot.observed_at,
                    trust_score=snapshot.trust_score,
                ),
            ),
            features={
                "spread_bps": snapshot.spread_bps,
                "estimated_slippage_bps": snapshot.estimated_slippage_bps,
                "top_of_book_notional": snapshot.top_of_book_notional,
            },
            generated_at=context.created_at,
        )

    def _abstain(self, context: AgentContext, thesis: str, flag: str) -> AgentEvidence:
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=SignalIntent.FLAT,
            confidence=0.0,
            thesis=thesis,
            risk_flags=(flag,),
            sources=(
                EvidenceSource(
                    source_id=f"execution-quality:{context.symbol}:missing-or-invalid",
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=context.candles[-1].close_time,
                    trust_score=1.0,
                ),
            ),
            generated_at=context.created_at,
        )
