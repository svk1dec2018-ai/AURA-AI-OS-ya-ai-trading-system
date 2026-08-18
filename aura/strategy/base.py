from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from aura.domain.models import NormalizedCandle, StrategySignal


@dataclass(slots=True, frozen=True)
class StrategyRuntimeContext:
    """Read-only position state exposed to strategies for governed exit logic.

    The strategy receives no broker/session credentials and no portfolio-risk
    controls. It may request an exit, but the shared RiskEngine still decides the
    resulting order quantity/permission.
    """

    current_position_quantity: Decimal = Decimal(0)
    average_entry_price: Decimal = Decimal(0)
    bars_in_position: int = 0

    def __post_init__(self) -> None:
        if self.average_entry_price < 0:
            raise ValueError("average_entry_price cannot be negative")
        if self.bars_in_position < 0:
            raise ValueError("bars_in_position cannot be negative")
        if self.current_position_quantity == 0 and self.bars_in_position != 0:
            raise ValueError("flat strategy runtime context cannot have bars_in_position")
        if self.current_position_quantity != 0 and self.average_entry_price <= 0:
            raise ValueError("open position requires a positive average_entry_price")


class Strategy(ABC):
    strategy_id: str
    warmup_bars: int = 1

    @abstractmethod
    def on_closed_candle(self, history: Sequence[NormalizedCandle]) -> StrategySignal | None:
        """Return a signal using only closed candles already present in history."""
        raise NotImplementedError

    def on_closed_candle_with_context(
        self,
        history: Sequence[NormalizedCandle],
        runtime: StrategyRuntimeContext,
    ) -> StrategySignal | None:
        """Position-aware extension; legacy strategies keep their original behavior."""
        del runtime
        return self.on_closed_candle(history)
