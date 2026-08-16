from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from aura.domain.models import (
    NormalizedCandle,
    OrderRequest,
    PortfolioSnapshot,
    RiskDecision,
    Side,
    SignalIntent,
    StrategySignal,
)
from aura.risk.engine import RiskEngine
from aura.strategy.base import Strategy


@dataclass(slots=True, frozen=True)
class DecisionResult:
    signal: StrategySignal
    risk: RiskDecision
    order: OrderRequest | None


class DecisionPipeline:
    """The shared strategy -> risk -> order path for backtest and live runtimes."""

    def __init__(self, strategy: Strategy, risk_engine: RiskEngine) -> None:
        self.strategy = strategy
        self.risk_engine = risk_engine

    def evaluate_closed_candle(
        self,
        history: Sequence[NormalizedCandle],
        portfolio: PortfolioSnapshot,
        day_start_equity: Decimal,
        venue: str,
        requested_quantity: Decimal,
    ) -> DecisionResult | None:
        if not history or not history[-1].closed:
            return None

        signal = self.strategy.on_closed_candle(history)
        if signal is None or signal.intent == SignalIntent.FLAT:
            return None

        side = Side.BUY if signal.intent == SignalIntent.LONG else Side.SELL
        proposed = OrderRequest(
            symbol=signal.symbol,
            venue=venue,
            side=side,
            quantity=requested_quantity,
        )
        decision = self.risk_engine.evaluate(
            order=proposed,
            reference_price=signal.reference_price,
            portfolio=portfolio,
            day_start_equity=day_start_equity,
        )
        if not decision.approved:
            return DecisionResult(signal=signal, risk=decision, order=None)

        approved_order = proposed.model_copy(update={"quantity": decision.approved_quantity})
        return DecisionResult(signal=signal, risk=decision, order=approved_order)
