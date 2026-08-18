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
from aura.strategy.base import Strategy, StrategyRuntimeContext


@dataclass(slots=True, frozen=True)
class DecisionResult:
    signal: StrategySignal
    risk: RiskDecision
    order: OrderRequest | None


class DecisionPipeline:
    """Shared signal -> risk -> order path for backtest, agents and live runtimes."""

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
        current_position_quantity: Decimal = Decimal(0),
        position_average_price: Decimal = Decimal(0),
        bars_in_position: int = 0,
    ) -> DecisionResult | None:
        if not history or not history[-1].closed:
            return None

        runtime = StrategyRuntimeContext(
            current_position_quantity=current_position_quantity,
            average_entry_price=(
                position_average_price if current_position_quantity != 0 else Decimal(0)
            ),
            bars_in_position=(bars_in_position if current_position_quantity != 0 else 0),
        )
        signal = self.strategy.on_closed_candle_with_context(history, runtime)
        if signal is None:
            return None
        return self.evaluate_signal(
            signal=signal,
            portfolio=portfolio,
            day_start_equity=day_start_equity,
            venue=venue,
            requested_quantity=requested_quantity,
            current_position_quantity=current_position_quantity,
        )

    def evaluate_signal(
        self,
        *,
        signal: StrategySignal,
        portfolio: PortfolioSnapshot,
        day_start_equity: Decimal,
        venue: str,
        requested_quantity: Decimal,
        current_position_quantity: Decimal = Decimal(0),
    ) -> DecisionResult | None:
        """Evaluate governed entry or exit intent through one RiskEngine.

        `FLAT` remains an abstention by default. Only a signal with
        `exit_position=True` can request a close, preventing advisory FLAT votes
        from accidentally liquidating positions. Explicit exits are still passed
        through RiskEngine as risk-reducing orders; no strategy gets a bypass.
        """
        if signal.intent == SignalIntent.FLAT:
            if not signal.exit_position or current_position_quantity == 0:
                return None
            side = Side.SELL if current_position_quantity > 0 else Side.BUY
            close_quantity = abs(current_position_quantity)
            proposed = OrderRequest(
                symbol=signal.symbol,
                venue=venue,
                side=side,
                quantity=close_quantity,
            )
            decision = self.risk_engine.evaluate(
                order=proposed,
                reference_price=signal.reference_price,
                portfolio=portfolio,
                day_start_equity=day_start_equity,
                current_position_quantity=current_position_quantity,
            )
            if not decision.approved:
                return DecisionResult(signal=signal, risk=decision, order=None)
            approved_order = proposed.model_copy(
                update={"quantity": decision.approved_quantity}
            )
            return DecisionResult(signal=signal, risk=decision, order=approved_order)

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
            current_position_quantity=current_position_quantity,
        )
        if not decision.approved:
            return DecisionResult(signal=signal, risk=decision, order=None)

        approved_order = proposed.model_copy(update={"quantity": decision.approved_quantity})
        return DecisionResult(signal=signal, risk=decision, order=approved_order)
