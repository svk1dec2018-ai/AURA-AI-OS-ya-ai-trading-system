from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.domain.models import Fill, PortfolioSnapshot, Side


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: Decimal = Decimal("0")  # signed: long > 0, short < 0
    average_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    def unrealized_pnl(self, mark: Decimal) -> Decimal:
        if self.quantity == 0:
            return Decimal("0")
        return self.quantity * (mark - self.average_price)


class PortfolioLedger:
    def __init__(self, starting_cash: Decimal) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.positions: dict[str, Position] = {}
        self.realized_pnl = Decimal("0")
        self.fees_paid = Decimal("0")
        self._applied_fills: set[str] = set()
        self.peak_equity = starting_cash

    def apply_fill(self, fill: Fill) -> bool:
        """Apply each broker fill exactly once. Returns False for duplicates."""
        if fill.fill_id in self._applied_fills:
            return False

        position = self.positions.setdefault(fill.symbol, Position(symbol=fill.symbol))
        signed_delta = fill.quantity if fill.side == Side.BUY else -fill.quantity
        old_qty = position.quantity
        old_avg = position.average_price
        realized = Decimal("0")

        # Cash accounting works for long and short trades: buys consume cash, sells add cash.
        self.cash -= signed_delta * fill.price
        self.cash -= fill.fee
        self.fees_paid += fill.fee

        if old_qty == 0 or (old_qty > 0 and signed_delta > 0) or (old_qty < 0 and signed_delta < 0):
            new_qty = old_qty + signed_delta
            old_notional = abs(old_qty) * old_avg
            added_notional = abs(signed_delta) * fill.price
            position.average_price = (old_notional + added_notional) / abs(new_qty)
            position.quantity = new_qty
        else:
            closing_qty = min(abs(old_qty), abs(signed_delta))
            if old_qty > 0:
                realized = closing_qty * (fill.price - old_avg)
            else:
                realized = closing_qty * (old_avg - fill.price)

            new_qty = old_qty + signed_delta
            position.quantity = new_qty
            if new_qty == 0:
                position.average_price = Decimal("0")
            elif (old_qty > 0 and new_qty > 0) or (old_qty < 0 and new_qty < 0):
                # Partial reduction; remaining inventory keeps its historical basis.
                position.average_price = old_avg
            else:
                # Position crossed through zero; excess opens a new position at this fill price.
                position.average_price = fill.price

        position.realized_pnl += realized
        self.realized_pnl += realized - fill.fee
        self._applied_fills.add(fill.fill_id)
        return True

    def snapshot(self, marks: dict[str, Decimal]) -> PortfolioSnapshot:
        market_value = Decimal("0")
        gross = Decimal("0")
        unrealized = Decimal("0")

        for symbol, position in self.positions.items():
            if position.quantity == 0:
                continue
            if symbol not in marks:
                raise KeyError(f"missing mark for open position: {symbol}")
            mark = marks[symbol]
            value = position.quantity * mark
            market_value += value
            gross += abs(value)
            unrealized += position.unrealized_pnl(mark)

        equity = self.cash + market_value
        if equity > self.peak_equity:
            self.peak_equity = equity
        drawdown = (
            (self.peak_equity - equity) / self.peak_equity * Decimal("100")
            if self.peak_equity > 0
            else Decimal("0")
        )

        return PortfolioSnapshot(
            cash=self.cash,
            equity=equity,
            gross_exposure=gross,
            net_exposure=market_value,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            peak_equity=self.peak_equity,
            drawdown_pct=drawdown,
        )
