from decimal import Decimal

from aura.domain.models import Fill, Side
from aura.portfolio.ledger import PortfolioLedger


def fill(fid: str, side: Side, qty: str, price: str, fee: str = "0") -> Fill:
    return Fill(
        fill_id=fid,
        order_id=f"o-{fid}",
        symbol="X",
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        fee=Decimal(fee),
    )


def test_long_close_and_duplicate_fill() -> None:
    ledger = PortfolioLedger(Decimal("1000"))
    buy = fill("1", Side.BUY, "2", "100", "1")
    sell = fill("2", Side.SELL, "2", "120", "1")

    assert ledger.apply_fill(buy) is True
    assert ledger.apply_fill(buy) is False
    ledger.apply_fill(sell)

    snap = ledger.snapshot({"X": Decimal("120")})
    assert snap.cash == Decimal("1038")
    assert snap.equity == Decimal("1038")
    assert snap.realized_pnl == Decimal("38")
    assert snap.unrealized_pnl == Decimal("0")


def test_long_to_short_flip_sets_new_basis() -> None:
    ledger = PortfolioLedger(Decimal("1000"))
    ledger.apply_fill(fill("1", Side.BUY, "1", "100"))
    ledger.apply_fill(fill("2", Side.SELL, "3", "110"))

    position = ledger.positions["X"]
    assert position.quantity == Decimal("-2")
    assert position.average_price == Decimal("110")
    assert position.realized_pnl == Decimal("10")
    snap = ledger.snapshot({"X": Decimal("100")})
    assert snap.unrealized_pnl == Decimal("20")
