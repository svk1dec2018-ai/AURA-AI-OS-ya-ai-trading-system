from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from aura.domain.models import NormalizedCandle, StrategySignal


class Strategy(ABC):
    strategy_id: str
    warmup_bars: int = 1

    @abstractmethod
    def on_closed_candle(self, history: Sequence[NormalizedCandle]) -> StrategySignal | None:
        """Return a signal using only closed candles already present in history."""
        raise NotImplementedError
