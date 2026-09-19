from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from aura.domain.models import SignalIntent


class VoteQuality(str, Enum):
    READY = "READY"
    INSUFFICIENT = "INSUFFICIENT"
    CONFLICTED = "CONFLICTED"


class ModelVote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_key: str = Field(min_length=1)
    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    calibration: float = Field(default=0.5, ge=0.0, le=1.0)
    research_only: bool = False


class EnsembleDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    quality: VoteQuality
    participating_models: tuple[str, ...]
    long_score: float = Field(ge=0.0)
    short_score: float = Field(ge=0.0)
    flat_score: float = Field(ge=0.0)
    reasons: tuple[str, ...] = ()
    execution_authority: bool = False


class PrimeModelEnsemble:
    """Deterministic reliability/calibration-weighted model fusion."""

    def __init__(
        self,
        *,
        min_models: int = 2,
        min_directional_margin: float = 0.10,
        allow_research_only: bool = False,
    ) -> None:
        if min_models <= 0:
            raise ValueError("min_models must be positive")
        if not 0 <= min_directional_margin <= 1:
            raise ValueError("min_directional_margin must be between 0 and 1")
        self.min_models = min_models
        self.min_directional_margin = min_directional_margin
        self.allow_research_only = allow_research_only

    def decide(self, votes: tuple[ModelVote, ...]) -> EnsembleDecision:
        eligible = tuple(
            vote
            for vote in votes
            if self.allow_research_only or not vote.research_only
        )
        model_keys = tuple(vote.model_key for vote in eligible)
        if len(eligible) < self.min_models:
            return EnsembleDecision(
                intent=SignalIntent.FLAT,
                confidence=0.0,
                quality=VoteQuality.INSUFFICIENT,
                participating_models=model_keys,
                long_score=0.0,
                short_score=0.0,
                flat_score=0.0,
                reasons=(f"eligible models {len(eligible)} < {self.min_models}",),
            )

        scores = {
            SignalIntent.LONG: 0.0,
            SignalIntent.SHORT: 0.0,
            SignalIntent.FLAT: 0.0,
        }
        total_weight = 0.0
        for vote in eligible:
            weight = max(1e-12, vote.reliability * vote.calibration)
            scores[vote.intent] += weight * vote.confidence
            total_weight += weight

        if total_weight <= 0:
            return EnsembleDecision(
                intent=SignalIntent.FLAT,
                confidence=0.0,
                quality=VoteQuality.INSUFFICIENT,
                participating_models=model_keys,
                long_score=0.0,
                short_score=0.0,
                flat_score=0.0,
                reasons=("ensemble weight is zero",),
            )

        long_score = scores[SignalIntent.LONG] / total_weight
        short_score = scores[SignalIntent.SHORT] / total_weight
        flat_score = scores[SignalIntent.FLAT] / total_weight
        directional_margin = abs(long_score - short_score)
        if directional_margin < self.min_directional_margin:
            return EnsembleDecision(
                intent=SignalIntent.FLAT,
                confidence=max(long_score, short_score, flat_score),
                quality=VoteQuality.CONFLICTED,
                participating_models=model_keys,
                long_score=long_score,
                short_score=short_score,
                flat_score=flat_score,
                reasons=(
                    f"directional margin {directional_margin:.4f} "
                    f"< {self.min_directional_margin:.4f}",
                ),
            )

        intent = SignalIntent.LONG if long_score > short_score else SignalIntent.SHORT
        return EnsembleDecision(
            intent=intent,
            confidence=max(long_score, short_score),
            quality=VoteQuality.READY,
            participating_models=model_keys,
            long_score=long_score,
            short_score=short_score,
            flat_score=flat_score,
        )
