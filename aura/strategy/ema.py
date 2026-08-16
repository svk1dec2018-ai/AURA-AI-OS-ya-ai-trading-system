from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from aura.domain.models import NormalizedCandle, SignalIntent, StrategySignal
from aura.strategy.base import Strategy


def _ema(values: Sequence[Decimal], period: int) -> Decimal:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        raise ValueError("not enough values for EMA")
    seed = sum(values[:period], Decimal("0")) / Decimal(period)
    alpha = Decimal("2") / Decimal(period + 1)
    value = seed
    for price in values[period:]:
        value = alpha * price + (Decimal("1") - alpha) * value
    return value


class EmaCrossStrategy(Strategy):
    """Reference plumbing strategy only; not a production alpha claim."""

    strategy_id = "reference.ema_cross.v1"

    def __init__(self, fast: int = 8, slow: int = 21) -> None:
        if fast <= 0 or slow <= 0 or fast >= slow:
            raise ValueError("require 0 < fast < slow")
        self.fast = fast
        self.slow = slow
        self.warmup_bars = slow + 1

    def on_closed_candle(self, history: Sequence[NormalizedCandle]) -> StrategySignal | None:
        if len(history) < self.warmup_bars:
            return None
        if not all(c.closed for c in history[-self.warmup_bars :]):
            return None

        closes = [c.close for c in history]
        prev_closes = closes[:-1]
        fast_prev = _ema(prev_closes, self.fast)
        slow_prev = _ema(prev_closes, self.slow)
        fast_now = _ema(closes, self.fast)
        slow_now = _ema(closes, self.slow)
        latest = history[-1]

        if fast_prev <= slow_prev and fast_now > slow_now:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=latest.symbol,
                intent=SignalIntent.LONG,
                confidence=0.55,
                reference_price=latest.close,
                generated_at=latest.close_time,
                reason=f"EMA{self.fast} crossed above EMA{self.slow} on closed candle",
            )
        if fast_prev >= slow_prev and fast_now < slow_now:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=latest.symbol,
                intent=SignalIntent.SHORT,
                confidence=0.55,
                reference_price=latest.close,
                generated_at=latest.close_time,
                reason=f"EMA{self.fast} crossed below EMA{self.slow} on closed candle",
            )
        return None
