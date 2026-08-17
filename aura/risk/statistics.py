from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import NormalDist, fmean, stdev

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StatisticalRiskMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    observed_at: datetime
    samples: int = Field(gt=1)
    confidence: float = Field(gt=0.5, lt=1.0)
    historical_var_pct: float = Field(ge=0.0)
    historical_cvar_pct: float = Field(ge=0.0)
    parametric_var_pct: float = Field(ge=0.0)
    annualized_volatility_pct: float = Field(ge=0.0)
    max_drawdown_pct: float = Field(ge=0.0)

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("risk metric observed_at must be timezone-aware")
        return value


class StressScenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    shocks_pct: dict[str, Decimal]


class StressResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario: str
    pnl: Decimal
    loss_amount: Decimal = Field(ge=0)
    loss_pct_of_equity: Decimal = Field(ge=0)


@dataclass(slots=True, frozen=True)
class CorrelationPair:
    left: str
    right: str
    correlation: float


def calculate_statistical_risk(
    returns: list[float] | tuple[float, ...],
    *,
    observed_at: datetime,
    confidence: float = 0.95,
    periods_per_year: int = 252,
) -> StatisticalRiskMetrics:
    values = [float(value) for value in returns]
    if len(values) < 2:
        raise ValueError("statistical risk requires at least two returns")
    if not 0.5 < confidence < 1.0:
        raise ValueError("confidence must be between 0.5 and 1")
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    if any(not math.isfinite(value) or value <= -1.0 for value in values):
        raise ValueError("returns must be finite and greater than -100%")

    ordered = sorted(values)
    tail_probability = 1.0 - confidence
    threshold = _quantile(ordered, tail_probability)
    historical_var = max(0.0, -threshold) * 100.0
    tail = [value for value in values if value <= threshold]
    historical_cvar = max(0.0, -fmean(tail)) * 100.0 if tail else historical_var

    mean_return = fmean(values)
    sigma = stdev(values)
    z = NormalDist().inv_cdf(tail_probability)
    parametric_threshold = mean_return + z * sigma
    parametric_var = max(0.0, -parametric_threshold) * 100.0
    annualized_volatility = sigma * math.sqrt(periods_per_year) * 100.0
    max_drawdown = _max_drawdown(values) * 100.0

    return StatisticalRiskMetrics(
        observed_at=observed_at,
        samples=len(values),
        confidence=confidence,
        historical_var_pct=historical_var,
        historical_cvar_pct=historical_cvar,
        parametric_var_pct=parametric_var,
        annualized_volatility_pct=annualized_volatility,
        max_drawdown_pct=max_drawdown,
    )


def pairwise_correlations(
    return_series: dict[str, list[float] | tuple[float, ...]],
) -> tuple[CorrelationPair, ...]:
    symbols = sorted(return_series)
    if len(symbols) < 2:
        return ()
    lengths = {len(return_series[symbol]) for symbol in symbols}
    if len(lengths) != 1 or next(iter(lengths)) < 2:
        raise ValueError("correlation series must have equal length of at least two")

    pairs: list[CorrelationPair] = []
    for left_index, left in enumerate(symbols):
        for right in symbols[left_index + 1 :]:
            pairs.append(
                CorrelationPair(
                    left=left,
                    right=right,
                    correlation=_correlation(
                        [float(value) for value in return_series[left]],
                        [float(value) for value in return_series[right]],
                    ),
                )
            )
    return tuple(pairs)


def evaluate_stress_scenarios(
    *,
    position_values: dict[str, Decimal],
    equity: Decimal,
    scenarios: tuple[StressScenario, ...],
) -> tuple[StressResult, ...]:
    if equity <= 0:
        raise ValueError("stress testing requires positive equity")
    results: list[StressResult] = []
    for scenario in scenarios:
        pnl = sum(
            (
                position_values.get(symbol, Decimal(0))
                * shock_pct
                / Decimal(100)
                for symbol, shock_pct in scenario.shocks_pct.items()
            ),
            Decimal(0),
        )
        loss = max(Decimal(0), -pnl)
        results.append(
            StressResult(
                scenario=scenario.name,
                pnl=pnl,
                loss_amount=loss,
                loss_pct_of_equity=loss / equity * Decimal(100),
            )
        )
    results.sort(key=lambda result: (-result.loss_pct_of_equity, result.scenario))
    return tuple(results)


def _correlation(left: list[float], right: list[float]) -> float:
    mean_left = fmean(left)
    mean_right = fmean(right)
    numerator = sum(
        (left_value - mean_left) * (right_value - mean_right)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_ss = sum((value - mean_left) ** 2 for value in left)
    right_ss = sum((value - mean_right) ** 2 for value in right)
    denominator = math.sqrt(left_ss * right_ss)
    if denominator == 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            drawdown = max(drawdown, (peak - equity) / peak)
    return drawdown


def _quantile(ordered: list[float], probability: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
