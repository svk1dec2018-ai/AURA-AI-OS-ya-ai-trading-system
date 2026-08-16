from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.domain.models import OrderRequest, PortfolioSnapshot, RiskDecision, Side


@dataclass(slots=True, frozen=True)
class RiskLimits:
    max_order_notional_pct: Decimal = Decimal(2)
    max_gross_exposure_pct: Decimal = Decimal(100)
    max_drawdown_pct: Decimal = Decimal(10)
    max_daily_loss_pct: Decimal = Decimal(4)
    allow_short: bool = True


class RiskEngine:
    """Independent pre-trade risk gate.

    Strategy/agent code cannot bypass this class in the shared decision pipeline.
    Risk-reducing orders are distinguished from orders that add new exposure so
    that a kill switch or loss gate can still permit flattening without allowing
    a strategy to increase risk.
    """

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self.kill_switch = False
        self.kill_switch_reason = ""

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

    def evaluate(
        self,
        order: OrderRequest,
        reference_price: Decimal,
        portfolio: PortfolioSnapshot,
        day_start_equity: Decimal,
        current_position_quantity: Decimal = Decimal(0),
    ) -> RiskDecision:
        requested = order.quantity
        if reference_price <= 0:
            return self._decision(
                requested=requested,
                approved=Decimal(0),
                reason="invalid reference price",
            )

        closing_qty = self._closing_capacity(order.side, requested, current_position_quantity)
        opening_requested = requested - closing_qty

        # A pure reduction/flatten never adds gross exposure and must remain
        # available during protective gates. Broker/exchange validity is handled
        # by the execution adapter, not by this portfolio-risk decision.
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

        # If a sell closes a long and then crosses zero, only the excess is a
        # new short. Disallow that excess when the portfolio policy forbids shorts.
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

        max_order_notional = portfolio.equity * self.limits.max_order_notional_pct / Decimal(100)
        max_opening_by_order = max_order_notional / reference_price
        approved_opening = min(opening_requested, max_opening_by_order)

        # Closing exposure creates capacity before any same-order position flip.
        gross_after_close = max(
            Decimal(0),
            portfolio.gross_exposure - closing_qty * reference_price,
        )
        max_gross = portfolio.equity * self.limits.max_gross_exposure_pct / Decimal(100)
        gross_capacity = max(Decimal(0), max_gross - gross_after_close)
        approved_opening = min(approved_opening, gross_capacity / reference_price)

        approved_qty = closing_qty + max(Decimal(0), approved_opening)
        if approved_qty <= 0:
            return self._decision(
                requested=requested,
                approved=Decimal(0),
                reason="no exposure capacity remains",
            )

        reason = (
            "approved"
            if approved_qty == requested
            else "approved with risk sizing reduction"
        )
        return self._decision(
            requested=requested,
            approved=approved_qty,
            reason=reason,
        )
