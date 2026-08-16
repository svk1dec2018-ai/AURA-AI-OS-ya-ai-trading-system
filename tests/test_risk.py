from decimal import Decimal

from aura.domain.models import OrderRequest, PortfolioSnapshot, Side
from aura.risk.engine import RiskEngine, RiskLimits


def snapshot(equity: str = "10000", gross: str = "0", drawdown: str = "0") -> PortfolioSnapshot:
    eq = Decimal(equity)
    return PortfolioSnapshot(
        cash=eq,
        equity=eq,
        gross_exposure=Decimal(gross),
        net_exposure=Decimal(0),
        realized_pnl=Decimal(0),
        unrealized_pnl=Decimal(0),
        peak_equity=eq,
        drawdown_pct=Decimal(drawdown),
    )


def test_order_is_resized_to_notional_limit() -> None:
    engine = RiskEngine(RiskLimits(max_order_notional_pct=Decimal(2)))
    order = OrderRequest(symbol="X", venue="TEST", side=Side.BUY, quantity=Decimal(10))
    decision = engine.evaluate(order, Decimal(100), snapshot(), Decimal(10000))
    assert decision.approved
    assert decision.approved_quantity == Decimal(2)


def test_kill_switch_blocks_new_risk() -> None:
    engine = RiskEngine(RiskLimits())
    engine.engage_kill_switch("operator")
    order = OrderRequest(symbol="X", venue="TEST", side=Side.BUY, quantity=Decimal(1))
    decision = engine.evaluate(order, Decimal(100), snapshot(), Decimal(10000))
    assert not decision.approved
    assert "kill switch" in decision.reason


def test_kill_switch_still_allows_position_reduction() -> None:
    engine = RiskEngine(RiskLimits())
    engine.engage_kill_switch("operator")
    order = OrderRequest(symbol="X", venue="TEST", side=Side.SELL, quantity=Decimal(1))
    decision = engine.evaluate(
        order,
        Decimal(100),
        snapshot(gross="200"),
        Decimal(10000),
        current_position_quantity=Decimal(2),
    )
    assert decision.approved
    assert decision.approved_quantity == Decimal(1)
    assert "risk-reducing" in decision.reason


def test_short_disabled_allows_close_but_blocks_flip_short() -> None:
    engine = RiskEngine(RiskLimits(allow_short=False))
    order = OrderRequest(symbol="X", venue="TEST", side=Side.SELL, quantity=Decimal(3))
    decision = engine.evaluate(
        order,
        Decimal(100),
        snapshot(gross="100"),
        Decimal(10000),
        current_position_quantity=Decimal(1),
    )
    assert decision.approved
    assert decision.approved_quantity == Decimal(1)
    assert "short opening blocked" in decision.reason


def test_drawdown_gate_blocks_new_risk() -> None:
    engine = RiskEngine(RiskLimits(max_drawdown_pct=Decimal(10)))
    order = OrderRequest(symbol="X", venue="TEST", side=Side.BUY, quantity=Decimal(1))
    decision = engine.evaluate(
        order,
        Decimal(100),
        snapshot(drawdown="10"),
        Decimal(10000),
    )
    assert not decision.approved


def test_drawdown_gate_allows_flattening() -> None:
    engine = RiskEngine(RiskLimits(max_drawdown_pct=Decimal(10)))
    order = OrderRequest(symbol="X", venue="TEST", side=Side.SELL, quantity=Decimal(2))
    decision = engine.evaluate(
        order,
        Decimal(100),
        snapshot(gross="200", drawdown="15"),
        Decimal(10000),
        current_position_quantity=Decimal(2),
    )
    assert decision.approved
    assert decision.approved_quantity == Decimal(2)
