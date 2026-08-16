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

    def evaluate(
        self,
        order: OrderRequest,
        reference_price: Decimal,
        portfolio: PortfolioSnapshot,
        day_start_equity: Decimal,
    ) -> RiskDecision:
        requested = order.quantity
        if self.kill_switch:
            return RiskDecision(
                approved=False,
                reason=f"kill switch engaged: {self.kill_switch_reason}",
                requested_quantity=requested,
            )
        if reference_price <= 0:
            return RiskDecision(
                approved=False,
                reason="invalid reference price",
                requested_quantity=requested,
            )
        if portfolio.equity <= 0:
            return RiskDecision(
                approved=False,
                reason="portfolio equity is non-positive",
                requested_quantity=requested,
            )
        if not self.limits.allow_short and order.side == Side.SELL:
            return RiskDecision(
                approved=False,
                reason="short selling disabled by risk policy",
                requested_quantity=requested,
            )
        if portfolio.drawdown_pct >= self.limits.max_drawdown_pct:
            return RiskDecision(
                approved=False,
                reason="maximum drawdown threshold reached",
                requested_quantity=requested,
            )

        if day_start_equity > 0:
            daily_loss_pct = max(
                Decimal(0),
                (day_start_equity - portfolio.equity) / day_start_equity * Decimal(100),
            )
            if daily_loss_pct >= self.limits.max_daily_loss_pct:
                return RiskDecision(
                    approved=False,
                    reason="maximum daily loss threshold reached",
                    requested_quantity=requested,
                )

        order_notional = order.quantity * reference_price
        max_order_notional = portfolio.equity * self.limits.max_order_notional_pct / Decimal(100)
        if order_notional > max_order_notional:
            approved_qty = max_order_notional / reference_price
            if approved_qty <= 0:
                return RiskDecision(
                    approved=False,
                    reason="order exceeds maximum order notional",
                    requested_quantity=requested,
                )
        else:
            approved_qty = requested

        projected_gross = portfolio.gross_exposure + approved_qty * reference_price
        max_gross = portfolio.equity * self.limits.max_gross_exposure_pct / Decimal(100)
        if projected_gross > max_gross:
            remaining_notional = max(Decimal(0), max_gross - portfolio.gross_exposure)
            approved_qty = min(approved_qty, remaining_notional / reference_price)

        if approved_qty <= 0:
            return RiskDecision(
                approved=False,
                reason="no exposure capacity remains",
                requested_quantity=requested,
            )

        reason = "approved" if approved_qty == requested else "approved with risk sizing reduction"
        return RiskDecision(
            approved=True,
            reason=reason,
            requested_quantity=requested,
            approved_quantity=approved_qty,
        )
