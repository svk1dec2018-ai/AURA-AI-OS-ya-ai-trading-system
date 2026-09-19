from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from aura.domain.models import Fill, PortfolioSnapshot, Side
from aura.portfolio.instruments import (
    DEFAULT_INSTRUMENT_SPEC,
    AccountingMode,
    InstrumentLedgerSpec,
)


class Position(BaseModel):
    """Validated mutable position state with deterministic serialization."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    symbol: str = Field(min_length=1, max_length=120)
    quantity: Decimal = Decimal(0)
    average_price: Decimal = Field(default=Decimal(0), ge=0)
    realized_pnl: Decimal = Decimal(0)
    accounting: AccountingMode = AccountingMode.SPOT
    contract_multiplier: Decimal = Field(default=Decimal(1), gt=0)

    def unrealized_pnl(self, mark: Decimal) -> Decimal:
        if self.quantity == 0:
            return Decimal(0)
        return self.quantity * (mark - self.average_price) * self.contract_multiplier

    def risk_notional(self, mark: Decimal) -> Decimal:
        return self.quantity * mark * self.contract_multiplier


class PortfolioLedger:
    def __init__(
        self,
        starting_cash: Decimal,
        *,
        instrument_specs: dict[str, InstrumentLedgerSpec] | None = None,
    ) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.positions: dict[str, Position] = {}
        self.realized_pnl = Decimal(0)
        self.fees_paid = Decimal(0)
        self._applied_fills: set[str] = set()
        self.peak_equity = starting_cash
        self.instrument_specs = dict(instrument_specs or {})

    def instrument_spec(self, symbol: str) -> InstrumentLedgerSpec:
        return self.instrument_specs.get(symbol, DEFAULT_INSTRUMENT_SPEC)

    def apply_fill(self, fill: Fill) -> bool:
        """Apply each broker fill exactly once. Returns False for duplicates."""
        if fill.fill_id in self._applied_fills:
            return False

        spec = self.instrument_spec(fill.symbol)
        position = self.positions.get(fill.symbol)
        if position is None:
            position = Position(
                symbol=fill.symbol,
                accounting=spec.accounting,
                contract_multiplier=spec.contract_multiplier,
            )
            self.positions[fill.symbol] = position
        elif (
            position.accounting != spec.accounting
            or position.contract_multiplier != spec.contract_multiplier
        ):
            raise ValueError(f"instrument accounting changed for open symbol: {fill.symbol}")

        signed_delta = fill.quantity if fill.side == Side.BUY else -fill.quantity
        old_qty = position.quantity
        old_avg = position.average_price
        realized = Decimal(0)

        if old_qty == 0 or (old_qty > 0 and signed_delta > 0) or (old_qty < 0 and signed_delta < 0):
            new_qty = old_qty + signed_delta
            old_notional = abs(old_qty) * old_avg
            added_notional = abs(signed_delta) * fill.price
            position.average_price = (old_notional + added_notional) / abs(new_qty)
            position.quantity = new_qty
        else:
            closing_qty = min(abs(old_qty), abs(signed_delta))
            if old_qty > 0:
                realized = closing_qty * (fill.price - old_avg) * position.contract_multiplier
            else:
                realized = closing_qty * (old_avg - fill.price) * position.contract_multiplier

            new_qty = old_qty + signed_delta
            position.quantity = new_qty
            if new_qty == 0:
                position.average_price = Decimal(0)
            elif (old_qty > 0 and new_qty > 0) or (old_qty < 0 and new_qty < 0):
                position.average_price = old_avg
            else:
                position.average_price = fill.price

        if position.accounting in {AccountingMode.SPOT, AccountingMode.PREMIUM}:
            self.cash -= signed_delta * fill.price * position.contract_multiplier
        else:
            self.cash += realized
        self.cash -= fill.fee
        self.fees_paid += fill.fee

        position.realized_pnl += realized
        self.realized_pnl += realized - fill.fee
        self._applied_fills.add(fill.fill_id)
        return True

    def snapshot(self, marks: dict[str, Decimal]) -> PortfolioSnapshot:
        spot_market_value = Decimal(0)
        gross = Decimal(0)
        net_exposure = Decimal(0)
        unrealized = Decimal(0)
        derivative_unrealized = Decimal(0)
        position_values: dict[str, Decimal] = {}

        for symbol, position in self.positions.items():
            if position.quantity == 0:
                continue
            if symbol not in marks:
                raise KeyError(f"missing mark for open position: {symbol}")
            mark = marks[symbol]
            risk_value = position.risk_notional(mark)
            position_values[symbol] = risk_value
            net_exposure += risk_value
            gross += abs(risk_value)
            position_unrealized = position.unrealized_pnl(mark)
            unrealized += position_unrealized
            if position.accounting in {AccountingMode.SPOT, AccountingMode.PREMIUM}:
                spot_market_value += risk_value
            else:
                derivative_unrealized += position_unrealized

        equity = self.cash + spot_market_value + derivative_unrealized
        self.peak_equity = max(self.peak_equity, equity)
        drawdown = (
            (self.peak_equity - equity) / self.peak_equity * Decimal(100)
            if self.peak_equity > 0
            else Decimal(0)
        )

        return PortfolioSnapshot(
            cash=self.cash,
            equity=equity,
            gross_exposure=gross,
            net_exposure=net_exposure,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            peak_equity=self.peak_equity,
            drawdown_pct=drawdown,
            position_values=position_values,
        )
