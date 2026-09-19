from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.domain.models import SignalIntent


class ForecastEnsembleSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    horizon_steps: int = Field(gt=0)
    generated_at: datetime
    target_timestamp: datetime
    point_forecast: float
    q10: float
    q50: float
    q90: float
    disagreement_score: float = Field(ge=0.0, le=1.0)
    contributing_models: tuple[str, ...]
    total_weight: float = Field(gt=0.0)

    @field_validator("generated_at", "target_timestamp")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> ForecastEnsembleSnapshot:
        if self.target_timestamp <= self.generated_at:
            raise ValueError("forecast target must be after generation")
        if not self.q10 <= self.q50 <= self.q90:
            raise ValueError("forecast quantiles must be monotonic")
        if not self.contributing_models:
            raise ValueError("forecast ensemble must name contributing models")
        return self


class ForecastEnsembleSpecialist(SpecialistAgent):
    """Translate a calibrated probabilistic forecast ensemble into advisory evidence."""

    agent_id = "ensemble:forecast:v1"
    role = AgentRole.FORECAST

    def __init__(
        self,
        *,
        max_disagreement: float = 0.35,
        min_directional_move_pct: float = 0.001,
    ) -> None:
        if not 0 <= max_disagreement <= 1:
            raise ValueError("max_disagreement must be between 0 and 1")
        if min_directional_move_pct < 0:
            raise ValueError("min_directional_move_pct cannot be negative")
        self.max_disagreement = max_disagreement
        self.min_directional_move_pct = min_directional_move_pct

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        raw = context.metadata.get("forecast_ensemble")
        if raw is None:
            return self._abstain(context, "probabilistic forecast ensemble is missing", "forecast_missing")
        snapshot = ForecastEnsembleSnapshot.model_validate(raw)
        if snapshot.symbol != context.symbol:
            return self._abstain(context, "forecast symbol mismatch", "forecast_symbol_mismatch")
        if snapshot.generated_at > context.created_at:
            return self._abstain(context, "forecast was generated in the future", "forecast_future_data")

        current = float(context.candles[-1].close)
        if current <= 0:
            return self._abstain(context, "current reference price is invalid", "forecast_reference_invalid")
        median_move = (snapshot.q50 - current) / current
        flags: list[str] = []
        if snapshot.disagreement_score > self.max_disagreement:
            flags.append("forecast_model_disagreement")

        lower_above = snapshot.q10 > current
        upper_below = snapshot.q90 < current
        if snapshot.disagreement_score > self.max_disagreement:
            intent = SignalIntent.FLAT
            thesis = "forecast models disagree beyond the allowed threshold"
            confidence = 0.0
        elif lower_above and median_move >= self.min_directional_move_pct:
            intent = SignalIntent.LONG
            thesis = "ensemble forecast distribution is fully above the current reference price"
            confidence = min(abs(median_move) * 20.0 * (1.0 - snapshot.disagreement_score), 1.0)
        elif upper_below and median_move <= -self.min_directional_move_pct:
            intent = SignalIntent.SHORT
            thesis = "ensemble forecast distribution is fully below the current reference price"
            confidence = min(abs(median_move) * 20.0 * (1.0 - snapshot.disagreement_score), 1.0)
        else:
            intent = SignalIntent.FLAT
            thesis = "forecast interval overlaps the current price or directional move is too small"
            confidence = 0.0

        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=intent,
            confidence=confidence,
            thesis=thesis,
            risk_flags=tuple(sorted(flags)),
            sources=tuple(
                EvidenceSource(
                    source_id=f"forecast-model:{model_key}",
                    source_type=EvidenceSourceType.RESEARCH,
                    observed_at=snapshot.generated_at,
                    trust_score=min(snapshot.total_weight / len(snapshot.contributing_models), 1.0),
                )
                for model_key in snapshot.contributing_models
            ),
            features={
                "horizon_steps": snapshot.horizon_steps,
                "target_timestamp": snapshot.target_timestamp.isoformat(),
                "point_forecast": snapshot.point_forecast,
                "q10": snapshot.q10,
                "q50": snapshot.q50,
                "q90": snapshot.q90,
                "disagreement_score": snapshot.disagreement_score,
                "models": snapshot.contributing_models,
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
                    source_id=f"forecast:{context.symbol}:missing-or-invalid",
                    source_type=EvidenceSourceType.RESEARCH,
                    observed_at=context.candles[-1].close_time,
                    trust_score=1.0,
                ),
            ),
            generated_at=context.created_at,
        )
