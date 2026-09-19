from datetime import UTC, datetime
from decimal import Decimal

from aura.risk.statistics import (
    StressScenario,
    calculate_statistical_risk,
    evaluate_stress_scenarios,
    pairwise_correlations,
)


def test_var_cvar_volatility_and_drawdown_are_computed_deterministically() -> None:
    returns = [0.01, -0.02, 0.005, -0.03, 0.015, -0.01, 0.02, -0.005]
    metrics = calculate_statistical_risk(
        returns,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        confidence=0.95,
        periods_per_year=252,
    )
    assert metrics.samples == len(returns)
    assert metrics.historical_cvar_pct >= metrics.historical_var_pct
    assert metrics.parametric_var_pct >= 0
    assert metrics.annualized_volatility_pct > 0
    assert metrics.max_drawdown_pct > 0


def test_pairwise_correlation_detects_positive_and_negative_relationships() -> None:
    pairs = pairwise_correlations(
        {
            "A": [0.01, 0.02, -0.01, 0.03],
            "B": [0.02, 0.04, -0.02, 0.06],
            "C": [-0.01, -0.02, 0.01, -0.03],
        }
    )
    by_pair = {(pair.left, pair.right): pair.correlation for pair in pairs}
    assert by_pair[("A", "B")] > 0.99
    assert by_pair[("A", "C")] < -0.99


def test_stress_scenarios_use_signed_market_values() -> None:
    results = evaluate_stress_scenarios(
        position_values={
            "XAUUSD": Decimal(6000),
            "BTCUSDT": Decimal(-2000),
        },
        equity=Decimal(10000),
        scenarios=(
            StressScenario(
                name="risk-off",
                shocks_pct={"XAUUSD": Decimal(-5), "BTCUSDT": Decimal(-10)},
            ),
            StressScenario(
                name="gold-crash",
                shocks_pct={"XAUUSD": Decimal(-15)},
            ),
        ),
    )
    assert results[0].scenario == "gold-crash"
    assert results[0].loss_amount == Decimal(900)
    assert results[0].loss_pct_of_equity == Decimal(9)
    assert results[1].loss_amount == Decimal(100)
