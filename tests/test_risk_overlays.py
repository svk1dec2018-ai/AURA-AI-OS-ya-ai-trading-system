from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.domain.models import OrderRequest, PortfolioSnapshot, Side
from aura.risk.engine import RiskEngine, RiskLimits
from aura.risk.overlays import StatisticalRiskLimits, StatisticalRiskOverlay
from aura.risk.statistics import StatisticalRiskMetrics


def _portfolio(*, position_values=None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=Decimal(10000),
        equity=Decimal(10000),
        gross_exposure=Decimal(0),
        net_exposure=Decimal(0),
        realized_pnl=Decimal(0),
        unrealized_pnl=Decimal(0),
        peak_equity=Decimal(10000),
        drawdown_pct=Decimal(0),
        position_values=position_values or {},
    )


def _order(*, created_at=None, side=Side.BUY, quantity="10") -> OrderRequest:
    return OrderRequest(
        order_id="o-1",
        client_order_id="c-1",
        symbol="X",
        venue="TEST",
        side=side,
        quantity=Decimal(quantity),
        created_at=created_at or datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )


def _metrics(observed_at, *, var=1.0, cvar=2.0):
    return StatisticalRiskMetrics(
        observed_at=observed_at,
        samples=100,
        confidence=0.95,
        historical_var_pct=var,
        historical_cvar_pct=cvar,
        parametric_var_pct=1.5,
        annualized_volatility_pct=20,
        max_drawdown_pct=5,
    )


def test_statistical_overlay_blocks_new_risk_when_cvar_exceeds_limit() -> None:
    observed = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
    overlay = StatisticalRiskOverlay(
        StatisticalRiskLimits(max_historical_cvar_pct=3.0, max_age=timedelta(hours=2))
    )
    overlay.update(_metrics(observed, cvar=4.0))
    risk = RiskEngine(
        RiskLimits(max_order_notional_pct=Decimal(100)),
        overlays=(overlay,),
    )
    decision = risk.evaluate(
        order=_order(),
        reference_price=Decimal(100),
        portfolio=_portfolio(),
        day_start_equity=Decimal(10000),
    )
    assert not decision.approved
    assert "CVaR" in decision.reason


def test_statistical_overlay_never_blocks_pure_flattening() -> None:
    observed = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
    overlay = StatisticalRiskOverlay(StatisticalRiskLimits(max_historical_cvar_pct=1.0))
    overlay.update(_metrics(observed, cvar=50.0))
    risk = RiskEngine(RiskLimits(), overlays=(overlay,))
    decision = risk.evaluate(
        order=_order(side=Side.SELL, quantity="5"),
        reference_price=Decimal(100),
        portfolio=_portfolio(position_values={"X": Decimal(500)}),
        day_start_equity=Decimal(10000),
        current_position_quantity=Decimal(5),
    )
    assert decision.approved
    assert decision.approved_quantity == Decimal(5)
    assert "risk-reducing" in decision.reason


def test_stale_statistical_state_blocks_new_risk() -> None:
    observed = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    overlay = StatisticalRiskOverlay(StatisticalRiskLimits(max_age=timedelta(hours=1)))
    overlay.update(_metrics(observed))
    risk = RiskEngine(RiskLimits(), overlays=(overlay,))
    decision = risk.evaluate(
        order=_order(created_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)),
        reference_price=Decimal(100),
        portfolio=_portfolio(),
        day_start_equity=Decimal(10000),
    )
    assert not decision.approved
    assert "stale" in decision.reason


def test_symbol_concentration_cap_resizes_order() -> None:
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(100),
            max_symbol_exposure_pct=Decimal(10),
        )
    )
    decision = risk.evaluate(
        order=_order(quantity="20"),
        reference_price=Decimal(100),
        portfolio=_portfolio(position_values={"X": Decimal(600)}),
        day_start_equity=Decimal(10000),
    )
    assert decision.approved
    assert decision.approved_quantity == Decimal(4)
