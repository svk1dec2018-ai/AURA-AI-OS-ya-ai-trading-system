from decimal import Decimal

from aura.domain.models import Fill, OrderRequest, PortfolioSnapshot, Side
from aura.portfolio.instruments import AccountingMode, InstrumentLedgerSpec
from aura.portfolio.ledger import PortfolioLedger
from aura.risk.engine import RiskEngine, RiskLimits


def _fill(fill_id: str, side: Side, quantity: str, price: str) -> Fill:
    return Fill(
        fill_id=fill_id,
        order_id=f"order-{fill_id}",
        symbol="XAUUSD",
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
    )


def test_derivative_ledger_uses_multiplier_without_exchanging_full_principal() -> None:
    ledger = PortfolioLedger(
        Decimal(10000),
        instrument_specs={
            "XAUUSD": InstrumentLedgerSpec(
                accounting=AccountingMode.DERIVATIVE,
                contract_multiplier=Decimal(100),
            )
        },
    )
    ledger.apply_fill(_fill("1", Side.BUY, "0.10", "2000"))
    opened = ledger.snapshot({"XAUUSD": Decimal(2000)})
    assert opened.cash == Decimal(10000)
    assert opened.equity == Decimal(10000)
    assert opened.gross_exposure == Decimal(20000)

    moved = ledger.snapshot({"XAUUSD": Decimal(2010)})
    assert moved.unrealized_pnl == Decimal(100)
    assert moved.equity == Decimal(10100)

    ledger.apply_fill(_fill("2", Side.SELL, "0.10", "2010"))
    closed = ledger.snapshot({"XAUUSD": Decimal(2010)})
    assert closed.cash == Decimal(10100)
    assert closed.equity == Decimal(10100)
    assert closed.realized_pnl == Decimal(100)


def test_premium_instrument_exchanges_premium_times_lot_multiplier() -> None:
    ledger = PortfolioLedger(
        Decimal(10000),
        instrument_specs={
            "NIFTY_CE": InstrumentLedgerSpec(
                accounting=AccountingMode.PREMIUM,
                contract_multiplier=Decimal(75),
            )
        },
    )
    fill = Fill(
        fill_id="opt-1",
        order_id="order-opt-1",
        symbol="NIFTY_CE",
        side=Side.BUY,
        quantity=Decimal(1),
        price=Decimal(100),
    )
    ledger.apply_fill(fill)
    snapshot = ledger.snapshot({"NIFTY_CE": Decimal(110)})
    assert snapshot.cash == Decimal(2500)
    assert snapshot.equity == Decimal(10750)
    assert snapshot.unrealized_pnl == Decimal(750)
    assert snapshot.gross_exposure == Decimal(8250)


def test_risk_engine_sizes_against_contract_notional() -> None:
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(10),
            max_gross_exposure_pct=Decimal(100),
            max_symbol_exposure_pct=Decimal(100),
        ),
        notional_multipliers={"XAUUSD": Decimal(100)},
    )
    portfolio = PortfolioSnapshot(
        cash=Decimal(10000),
        equity=Decimal(10000),
        gross_exposure=Decimal(0),
        net_exposure=Decimal(0),
        realized_pnl=Decimal(0),
        unrealized_pnl=Decimal(0),
        peak_equity=Decimal(10000),
        drawdown_pct=Decimal(0),
    )
    order = OrderRequest(
        symbol="XAUUSD",
        venue="MT5_DEMO",
        side=Side.BUY,
        quantity=Decimal(1),
    )
    decision = risk.evaluate(
        order,
        reference_price=Decimal(2000),
        portfolio=portfolio,
        day_start_equity=Decimal(10000),
    )
    assert decision.approved
    assert decision.approved_quantity == Decimal("0.005")
