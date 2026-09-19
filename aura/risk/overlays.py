from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from aura.domain.models import OrderRequest, PortfolioSnapshot
from aura.risk.statistics import StatisticalRiskMetrics, StressResult


class RiskOverlayDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allow_new_risk: bool
    reason: str


class PreTradeRiskOverlay(Protocol):
    def evaluate(
        self,
        *,
        order: OrderRequest,
        reference_price,
        portfolio: PortfolioSnapshot,
        current_position_quantity,
    ) -> RiskOverlayDecision: ...


@dataclass(slots=True, frozen=True)
class StatisticalRiskLimits:
    max_historical_var_pct: float = 5.0
    max_historical_cvar_pct: float = 8.0
    max_parametric_var_pct: float = 5.0
    max_annualized_volatility_pct: float = 100.0
    max_statistical_drawdown_pct: float = 20.0
    max_stress_loss_pct: float = 12.0
    max_age: timedelta = timedelta(hours=24)
    require_state: bool = True

    def __post_init__(self) -> None:
        numeric = (
            self.max_historical_var_pct,
            self.max_historical_cvar_pct,
            self.max_parametric_var_pct,
            self.max_annualized_volatility_pct,
            self.max_statistical_drawdown_pct,
            self.max_stress_loss_pct,
        )
        if any(value < 0 for value in numeric):
            raise ValueError("statistical risk limits cannot be negative")
        if self.max_age < timedelta(0):
            raise ValueError("statistical risk max_age cannot be negative")


class StatisticalRiskOverlay:
    """Block new risk when deterministic portfolio/tail metrics exceed policy."""

    def __init__(self, limits: StatisticalRiskLimits | None = None) -> None:
        self.limits = limits or StatisticalRiskLimits()
        self.metrics: StatisticalRiskMetrics | None = None
        self.stress_results: tuple[StressResult, ...] = ()

    def update(
        self,
        metrics: StatisticalRiskMetrics,
        *,
        stress_results: tuple[StressResult, ...] = (),
    ) -> None:
        self.metrics = metrics
        self.stress_results = stress_results

    def evaluate(
        self,
        *,
        order: OrderRequest,
        reference_price,
        portfolio: PortfolioSnapshot,
        current_position_quantity,
    ) -> RiskOverlayDecision:
        del reference_price, portfolio, current_position_quantity
        if self.metrics is None:
            return RiskOverlayDecision(
                allow_new_risk=not self.limits.require_state,
                reason=(
                    "statistical risk state unavailable"
                    if self.limits.require_state
                    else "statistical risk state optional"
                ),
            )
        if self.metrics.observed_at > order.created_at:
            return RiskOverlayDecision(
                allow_new_risk=False,
                reason="statistical risk state is from the future",
            )
        age = order.created_at - self.metrics.observed_at
        if age > self.limits.max_age:
            return RiskOverlayDecision(
                allow_new_risk=False,
                reason=f"statistical risk state stale by {age}",
            )

        checks = (
            (
                self.metrics.historical_var_pct,
                self.limits.max_historical_var_pct,
                "historical VaR",
            ),
            (
                self.metrics.historical_cvar_pct,
                self.limits.max_historical_cvar_pct,
                "historical CVaR",
            ),
            (
                self.metrics.parametric_var_pct,
                self.limits.max_parametric_var_pct,
                "parametric VaR",
            ),
            (
                self.metrics.annualized_volatility_pct,
                self.limits.max_annualized_volatility_pct,
                "annualized volatility",
            ),
            (
                self.metrics.max_drawdown_pct,
                self.limits.max_statistical_drawdown_pct,
                "statistical max drawdown",
            ),
        )
        for actual, limit, label in checks:
            if actual > limit:
                return RiskOverlayDecision(
                    allow_new_risk=False,
                    reason=f"{label} {actual:.4f}% exceeds {limit:.4f}%",
                )

        worst_stress = max(
            (float(result.loss_pct_of_equity) for result in self.stress_results),
            default=0.0,
        )
        if worst_stress > self.limits.max_stress_loss_pct:
            return RiskOverlayDecision(
                allow_new_risk=False,
                reason=(
                    f"stress loss {worst_stress:.4f}% exceeds "
                    f"{self.limits.max_stress_loss_pct:.4f}%"
                ),
            )
        return RiskOverlayDecision(allow_new_risk=True, reason="statistical risk within limits")
