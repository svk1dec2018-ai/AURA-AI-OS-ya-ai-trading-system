from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.domain.models import OrderRequest, PortfolioSnapshot, RiskDecision, Side
from aura.risk.overlays import PreTradeRiskOverlay
from aura.risk.quantity import QuantityRule


@dataclass(slots=True, frozen=True)
class RiskLimits:
    max_order_notional_pct: Decimal = Decimal(2)
    max_risk_per_trade_pct: Decimal | None = None
    max_gross_exposure_pct: Decimal = Decimal(100)
    max_symbol_exposure_pct: Decimal = Decimal(100)
    max_drawdown_pct: Decimal = Decimal(10)
    max_daily_loss_pct: Decimal = Decimal(4)
    allow_short: bool = True

    def __post_init__(self) -> None:
        percentages = {
            "max_order_notional_pct": self.max_order_notional_pct,
            "max_gross_exposure_pct": self.max_gross_exposure_pct,
            "max_symbol_exposure_pct": self.max_symbol_exposure_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
        }
        if any(value < 0 for value in percentages.values()):
            raise ValueError("risk limit percentages cannot be negative")
        if self.max_risk_per_trade_pct is not None and not (
            Decimal(0) < self.max_risk_per_trade_pct <= Decimal(100)
        ):
            raise ValueError("max_risk_per_trade_pct must be in (0, 100]")


class RiskEngine:
    """Independent pre-trade risk gate with contract and broker-grid sizing."""

    def __init__(
        self,
        limits: RiskLimits,
        *,
        overlays: tuple[PreTradeRiskOverlay, ...] = (),
        notional_multipliers: dict[str, Decimal] | None = None,
        quantity_rules: dict[str, QuantityRule] | None = None,
    ) -> None:
        self.limits = limits
        self.overlays = overlays
        self.notional_multipliers = dict(notional_multipliers or {})
        self.quantity_rules = dict(quantity_rules or {})
        if any(value <= 0 for value in self.notional_multipliers.values()):
            raise ValueError("risk notional multipliers must be positive")
        self.kill_switch = False
        self.kill_switch_reason = ""

    def notional_multiplier(self, symbol: str) -> Decimal:
        return self.notional_multipliers.get(symbol, Decimal(1))

    def engage_kill_switch(self, reason: str) -> None:
        self.kill_switch = True
        self.kill_switch_reason = reason or "manual kill switch"

    def reset_kill_switch(self) -> None:
        self.kill_switch = False
        self.kill_switch_reason = ""

    @staticmethod
    def _closing_capacity(
        side: Side,
        requested: Decimal,
        current_position_quantity: Decimal,
    ) -> Decimal:
        if current_position_quantity > 0 and side == Side.SELL:
            return min(requested, current_position_quantity)
        if current_position_quantity < 0 and side == Side.BUY:
            return min(requested, abs(current_position_quantity))
        return Decimal(0)

    @staticmethod
    def _decision(
        *,
        requested: Decimal,
        approved: Decimal,
        reason: str,
    ) -> RiskDecision:
        return RiskDecision(
            approved=approved > 0,
            reason=reason,
            requested_quantity=requested,
            approved_quantity=max(Decimal(0), approved),
        )

    def _normalize_opening_quantity(
        self,
        symbol: str,
        *,
        closing_qty: Decimal,
        total_approved_qty: Decimal,
    ) -> Decimal:
        opening_qty = max(Decimal(0), total_approved_qty - closing_qty)
        rule = self.quantity_rules.get(symbol)
        if rule is None or opening_qty <= 0:
            return closing_qty + opening_qty
        return closing_qty + rule.normalize_down(opening_qty)

    def evaluate(
        self,
        order: OrderRequest,
        reference_price: Decimal,
        portfolio: PortfolioSnapshot,
        day_start_equity: Decimal,
        current_position_quantity: Decimal = Decimal(0),
        protective_stop_price: Decimal | None = None,
    ) -> RiskDecision:
        requested = order.quantity
        if reference_price <= 0:
            return self._decision(
                requested=requested,
                approved=Decimal(0),
                reason="invalid reference price",
            )

        unit_notional = reference_price * self.notional_multiplier(order.symbol)
        closing_qty = self._closing_capacity(order.side, requested, current_position_quantity)
        opening_requested = requested - closing_qty

        if opening_requested <= 0:
            return self._decision(
                requested=requested,
                approved=requested,
                reason="approved risk-reducing order",
            )

        if self.kill_switch:
            return self._decision(
                requested=requested,
                approved=closing_qty,
                reason=(
                    "kill switch: only risk-reducing quantity approved"
                    if closing_qty > 0
                    else f"kill switch engaged: {self.kill_switch_reason}"
                ),
            )

        if portfolio.equity <= 0:
            return self._decision(
                requested=requested,
                approved=closing_qty,
                reason="portfolio equity is non-positive; new exposure blocked",
            )

        if not self.limits.allow_short and order.side == Side.SELL:
            return self._decision(
                requested=requested,
                approved=closing_qty,
                reason=(
                    "short opening blocked; closing quantity approved"
                    if closing_qty > 0
                    else "short selling disabled by risk policy"
                ),
            )

        if portfolio.drawdown_pct >= self.limits.max_drawdown_pct:
            return self._decision(
                requested=requested,
                approved=closing_qty,
                reason="maximum drawdown reached; only risk reduction approved",
            )

        if day_start_equity > 0:
            daily_loss_pct = max(
                Decimal(0),
                (day_start_equity - portfolio.equity) / day_start_equity * Decimal(100),
            )
            if daily_loss_pct >= self.limits.max_daily_loss_pct:
                return self._decision(
                    requested=requested,
                    approved=closing_qty,
                    reason="maximum daily loss reached; only risk reduction approved",
                )

        for overlay in self.overlays:
            overlay_decision = overlay.evaluate(
                order=order,
                reference_price=reference_price,
                portfolio=portfolio,
                current_position_quantity=current_position_quantity,
            )
            if not overlay_decision.allow_new_risk:
                return self._decision(
                    requested=requested,
                    approved=closing_qty,
                    reason=f"risk overlay blocked new exposure: {overlay_decision.reason}",
                )

        max_order_notional = portfolio.equity * self.limits.max_order_notional_pct / Decimal(100)
        approved_opening = min(opening_requested, max_order_notional / unit_notional)

        if self.limits.max_risk_per_trade_pct is not None:
            if protective_stop_price is None or protective_stop_price <= 0:
                return self._decision(
                    requested=requested,
                    approved=closing_qty,
                    reason="protective stop required for per-trade risk sizing",
                )
            stop_is_adverse = (
                order.side == Side.BUY and protective_stop_price < reference_price
            ) or (order.side == Side.SELL and protective_stop_price > reference_price)
            if not stop_is_adverse:
                return self._decision(
                    requested=requested,
                    approved=closing_qty,
                    reason="protective stop must be adverse to the opening direction",
                )
            loss_per_unit = (
                abs(reference_price - protective_stop_price)
                * self.notional_multiplier(order.symbol)
            )
            risk_budget = (
                portfolio.equity
                * self.limits.max_risk_per_trade_pct
                / Decimal(100)
            )
            approved_opening = min(approved_opening, risk_budget / loss_per_unit)

        gross_after_close = max(
            Decimal(0),
            portfolio.gross_exposure - closing_qty * unit_notional,
        )
        max_gross = portfolio.equity * self.limits.max_gross_exposure_pct / Decimal(100)
        gross_capacity = max(Decimal(0), max_gross - gross_after_close)
        approved_opening = min(approved_opening, gross_capacity / unit_notional)

        current_symbol_value = abs(portfolio.position_values.get(order.symbol, Decimal(0)))
        symbol_value_after_close = max(
            Decimal(0),
            current_symbol_value - closing_qty * unit_notional,
        )
        max_symbol_value = (
            portfolio.equity * self.limits.max_symbol_exposure_pct / Decimal(100)
        )
        symbol_capacity = max(Decimal(0), max_symbol_value - symbol_value_after_close)
        approved_opening = min(approved_opening, symbol_capacity / unit_notional)

        economically_approved = closing_qty + max(Decimal(0), approved_opening)
        if economically_approved <= 0:
            return self._decision(
                requested=requested,
                approved=Decimal(0),
                reason="risk capacity exhausted",
            )
        approved_qty = self._normalize_opening_quantity(
            order.symbol,
            closing_qty=closing_qty,
            total_approved_qty=economically_approved,
        )
        if approved_qty <= 0:
            return self._decision(
                requested=requested,
                approved=Decimal(0),
                reason="risk capacity is below broker minimum quantity",
            )

        reason = "approved" if approved_qty == requested else "approved with risk sizing reduction"
        return self._decision(
            requested=requested,
            approved=approved_qty,
            reason=reason,
        )
