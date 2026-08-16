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


def test_kill_switch_blocks_all_orders() -> None:
    engine = RiskEngine(RiskLimits())
    engine.engage_kill_switch("operator")
    order = OrderRequest(symbol="X", venue="TEST", side=Side.BUY, quantity=Decimal(1))
    decision = engine.evaluate(order, Decimal(100), snapshot(), Decimal(10000))
    assert not decision.approved
    assert "kill switch" in decision.reason


def test_drawdown_gate_blocks_order() -> None:
    engine = RiskEngine(RiskLimits(max_drawdown_pct=Decimal(10)))
    order = OrderRequest(symbol="X", venue="TEST", side=Side.BUY, quantity=Decimal(1))
    decision = engine.evaluate(
        order,
        Decimal(100),
        snapshot(drawdown="10"),
        Decimal(10000),
    )
    assert not decision.approved
