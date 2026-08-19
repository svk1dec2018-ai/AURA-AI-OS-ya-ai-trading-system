from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.evolution.core import PerformanceSlice

_UNCLASSIFIED_REGIMES = frozenset({"UNKNOWN", "UNCLASSIFIED"})


def _normalize_regime(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("regime must not be empty")
    if normalized in _UNCLASSIFIED_REGIMES:
        raise ValueError("unclassified observations cannot be used as regime evidence")
    return normalized


class RegimePerformanceEvidence(BaseModel):
    """One immutable, pre-aggregated performance slice for a classified regime."""

    model_config = ConfigDict(frozen=True)

    regime: str
    performance: PerformanceSlice
    source_artifact_id: str = Field(min_length=1)

    @field_validator("regime")
    @classmethod
    def normalize_regime(cls, value: str) -> str:
        return _normalize_regime(value)

    @field_validator("source_artifact_id")
    @classmethod
    def normalize_artifact_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source_artifact_id must not be blank")
        return normalized

    @model_validator(mode="after")
    def require_finite_metrics(self) -> RegimePerformanceEvidence:
        metrics = (
            self.performance.net_return_pct,
            self.performance.expectancy_pct,
            self.performance.profit_factor,
            self.performance.max_drawdown_pct,
            self.performance.sharpe,
            self.performance.win_rate,
            self.performance.avg_slippage_bps,
        )
        if any(not math.isfinite(value) for value in metrics):
            raise ValueError("regime performance metrics must be finite")
        return self


@dataclass(slots=True, frozen=True)
class RegimeStabilityPolicy:
    """Conservative thresholds for already-measured regime evidence."""

    required_regimes: tuple[str, ...] = ("TREND", "CHOP")
    min_trades_per_regime: int = 30
    min_total_trades: int = 60
    min_passing_regime_fraction: float = 1.0
    min_expectancy_pct: float = 0.0
    min_profit_factor: float = 1.05
    max_drawdown_pct: float = 20.0
    max_dominant_regime_trade_fraction: float = 0.70

    def __post_init__(self) -> None:
        normalized = tuple(_normalize_regime(value) for value in self.required_regimes)
        if not normalized:
            raise ValueError("at least one required regime is needed")
        if len(set(normalized)) != len(normalized):
            raise ValueError("required_regimes must be unique")
        object.__setattr__(self, "required_regimes", normalized)
        if self.min_trades_per_regime <= 0 or self.min_total_trades <= 0:
            raise ValueError("trade requirements must be positive")
        if not 0 < self.min_passing_regime_fraction <= 1:
            raise ValueError("min_passing_regime_fraction must be in (0, 1]")
        if any(
            not math.isfinite(value)
            for value in (
                self.min_expectancy_pct,
                self.min_profit_factor,
                self.max_drawdown_pct,
                self.max_dominant_regime_trade_fraction,
            )
        ):
            raise ValueError("performance thresholds must be finite")
        if self.min_profit_factor < 0 or self.max_drawdown_pct < 0:
            raise ValueError("performance thresholds cannot be negative")
        if not 0 < self.max_dominant_regime_trade_fraction <= 1:
            raise ValueError("max_dominant_regime_trade_fraction must be in (0, 1]")


class RegimeSegmentAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    regime: str
    required: bool
    trades: int = Field(ge=0)
    net_return_pct: float
    expectancy_pct: float
    profit_factor: float = Field(ge=0)
    max_drawdown_pct: float = Field(ge=0)
    passed: bool
    failures: tuple[str, ...]
    source_artifact_id: str


class RegimeStabilityAssessment(BaseModel):
    """Diagnostic research result; it is not a deployment or promotion approval."""

    model_config = ConfigDict(frozen=True)

    approved: bool
    required_regimes: tuple[str, ...]
    observed_regimes: tuple[str, ...]
    missing_regimes: tuple[str, ...]
    total_required_trades: int = Field(ge=0)
    dominant_regime_trade_fraction: float | None = Field(default=None, ge=0, le=1)
    passing_required_regime_fraction: float = Field(ge=0, le=1)
    reasons: tuple[str, ...]
    segments: tuple[RegimeSegmentAssessment, ...]


def assess_regime_stability(
    evidence: list[RegimePerformanceEvidence] | tuple[RegimePerformanceEvidence, ...],
    *,
    policy: RegimeStabilityPolicy | None = None,
) -> RegimeStabilityAssessment:
    """Evaluate coverage and stability without classifying regimes or promoting a strategy."""

    limits = policy or RegimeStabilityPolicy()
    by_regime: dict[str, RegimePerformanceEvidence] = {}
    for item in evidence:
        if item.regime in by_regime:
            raise ValueError(f"duplicate aggregated evidence for regime {item.regime}")
        by_regime[item.regime] = item

    required = set(limits.required_regimes)
    missing = tuple(regime for regime in limits.required_regimes if regime not in by_regime)
    segments = tuple(
        _assess_segment(item, required=item.regime in required, policy=limits)
        for item in sorted(by_regime.values(), key=lambda value: value.regime)
    )
    required_segments = tuple(segment for segment in segments if segment.required)
    total_required_trades = sum(segment.trades for segment in required_segments)
    dominant_fraction = (
        max(segment.trades for segment in required_segments) / total_required_trades
        if total_required_trades
        else None
    )
    passing_fraction = sum(segment.passed for segment in required_segments) / len(
        limits.required_regimes
    )

    reasons: list[str] = []
    if missing:
        reasons.append("missing_required_regimes")
    if total_required_trades < limits.min_total_trades:
        reasons.append("insufficient_total_regime_trades")
    if (
        dominant_fraction is not None
        and dominant_fraction > limits.max_dominant_regime_trade_fraction
    ):
        reasons.append("regime_trade_concentration")
    if passing_fraction < limits.min_passing_regime_fraction:
        reasons.append("passing_regime_fraction_below_threshold")

    return RegimeStabilityAssessment(
        approved=not reasons,
        required_regimes=limits.required_regimes,
        observed_regimes=tuple(sorted(by_regime)),
        missing_regimes=missing,
        total_required_trades=total_required_trades,
        dominant_regime_trade_fraction=dominant_fraction,
        passing_required_regime_fraction=passing_fraction,
        reasons=tuple(reasons),
        segments=segments,
    )


def _assess_segment(
    evidence: RegimePerformanceEvidence,
    *,
    required: bool,
    policy: RegimeStabilityPolicy,
) -> RegimeSegmentAssessment:
    performance = evidence.performance
    failures: list[str] = []
    if performance.trades < policy.min_trades_per_regime:
        failures.append("insufficient_regime_trades")
    if performance.expectancy_pct <= policy.min_expectancy_pct:
        failures.append("non_positive_regime_expectancy")
    if performance.profit_factor < policy.min_profit_factor:
        failures.append("weak_regime_profit_factor")
    if performance.max_drawdown_pct > policy.max_drawdown_pct:
        failures.append("regime_drawdown")
    return RegimeSegmentAssessment(
        regime=evidence.regime,
        required=required,
        trades=performance.trades,
        net_return_pct=performance.net_return_pct,
        expectancy_pct=performance.expectancy_pct,
        profit_factor=performance.profit_factor,
        max_drawdown_pct=performance.max_drawdown_pct,
        passed=not failures,
        failures=tuple(failures),
        source_artifact_id=evidence.source_artifact_id,
    )
