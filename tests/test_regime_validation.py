from __future__ import annotations

import pytest
from pydantic import ValidationError

from aura.evolution.core import PerformanceSlice
from aura.research.regime_validation import (
    RegimePerformanceEvidence,
    RegimeStabilityPolicy,
    assess_regime_stability,
)


def _evidence(
    regime: str,
    *,
    trades: int = 40,
    expectancy: float = 0.20,
    profit_factor: float = 1.30,
    drawdown: float = 8.0,
) -> RegimePerformanceEvidence:
    return RegimePerformanceEvidence(
        regime=regime,
        source_artifact_id=f"oos-{regime.strip().lower()}",
        performance=PerformanceSlice(
            label=f"{regime} OOS",
            trades=trades,
            net_return_pct=4.0,
            expectancy_pct=expectancy,
            profit_factor=profit_factor,
            max_drawdown_pct=drawdown,
            sharpe=1.1,
            win_rate=0.55,
            avg_slippage_bps=2.0,
        ),
    )


def test_balanced_required_regimes_pass_research_gate() -> None:
    assessment = assess_regime_stability(
        (_evidence("trend"), _evidence(" CHOP "), _evidence("high_volatility")),
        policy=RegimeStabilityPolicy(
            required_regimes=("trend", "chop", "high_volatility"),
            min_total_trades=100,
            max_dominant_regime_trade_fraction=0.40,
        ),
    )

    assert assessment.approved
    assert assessment.reasons == ()
    assert assessment.observed_regimes == ("CHOP", "HIGH_VOLATILITY", "TREND")
    assert assessment.dominant_regime_trade_fraction == pytest.approx(1 / 3)


def test_missing_required_regime_fails_closed() -> None:
    assessment = assess_regime_stability(
        (_evidence("trend", trades=70),),
        policy=RegimeStabilityPolicy(required_regimes=("trend", "chop")),
    )

    assert not assessment.approved
    assert assessment.missing_regimes == ("CHOP",)
    assert "missing_required_regimes" in assessment.reasons
    assert "passing_regime_fraction_below_threshold" in assessment.reasons


def test_trade_concentration_cannot_mask_thin_regime() -> None:
    assessment = assess_regime_stability(
        (_evidence("trend", trades=90), _evidence("chop", trades=10)),
        policy=RegimeStabilityPolicy(
            min_trades_per_regime=10,
            min_total_trades=100,
            max_dominant_regime_trade_fraction=0.70,
        ),
    )

    assert not assessment.approved
    assert assessment.passing_required_regime_fraction == 1.0
    assert assessment.dominant_regime_trade_fraction == 0.9
    assert assessment.reasons == ("regime_trade_concentration",)


def test_weak_required_segment_reports_each_failed_threshold() -> None:
    assessment = assess_regime_stability(
        (
            _evidence("trend", trades=50),
            _evidence(
                "chop",
                trades=10,
                expectancy=-0.1,
                profit_factor=0.8,
                drawdown=25.0,
            ),
        )
    )

    chop = next(segment for segment in assessment.segments if segment.regime == "CHOP")
    assert not assessment.approved
    assert chop.failures == (
        "insufficient_regime_trades",
        "non_positive_regime_expectancy",
        "weak_regime_profit_factor",
        "regime_drawdown",
    )
    assert "passing_regime_fraction_below_threshold" in assessment.reasons


def test_extra_regime_does_not_mask_missing_required_regime() -> None:
    assessment = assess_regime_stability(
        (_evidence("trend"), _evidence("market_open", trades=200)),
        policy=RegimeStabilityPolicy(required_regimes=("trend", "chop")),
    )

    assert not assessment.approved
    assert assessment.missing_regimes == ("CHOP",)
    assert assessment.total_required_trades == 40
    assert next(item for item in assessment.segments if item.regime == "MARKET_OPEN").required is False


def test_duplicate_normalized_regime_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate aggregated evidence for regime TREND"):
        assess_regime_stability((_evidence("trend"), _evidence(" TREND ")))


@pytest.mark.parametrize("label", ["", "  ", "unknown", "UNCLASSIFIED"])
def test_unclassified_regime_evidence_is_rejected(label: str) -> None:
    with pytest.raises(ValidationError):
        _evidence(label)


def test_non_finite_performance_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="metrics must be finite"):
        _evidence("trend", profit_factor=float("inf"))


@pytest.mark.parametrize(
    "policy",
    [
        RegimeStabilityPolicy,
    ],
)
def test_policy_defaults_remain_constructible(policy: type[RegimeStabilityPolicy]) -> None:
    assert policy().required_regimes == ("TREND", "CHOP")


def test_invalid_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        RegimeStabilityPolicy(required_regimes=("trend", " TREND "))
    with pytest.raises(ValueError, match=r"must be in \(0, 1]"):
        RegimeStabilityPolicy(min_passing_regime_fraction=0)
    with pytest.raises(ValueError, match="thresholds must be finite"):
        RegimeStabilityPolicy(min_expectancy_pct=float("nan"))
