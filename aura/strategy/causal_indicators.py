"""Past-only indicators. Outputs belong to the latest confirmed candle.

These are native AURA implementations, not imports of vectorized historical
labels. No centered windows, negative shifts or retrospective signal relocation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

from aura.domain.models import NormalizedCandle


def choppiness(candles: Sequence[NormalizedCandle], *, period: int = 14) -> float | None:
    if period < 2:
        raise ValueError("choppiness period must be at least 2")
    if len(candles) < period + 1:
        return None
    window = candles[-(period + 1) :]
    extent = max(c.high for c in window[1:]) - min(c.low for c in window[1:])
    if extent <= 0:
        return 100.0
    total = sum(
        (
            max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
            for a, b in pairwise(window)
        ),
        Decimal(0),
    )
    if total <= 0:
        return 100.0
    return max(0.0, min(100.0, 100 * math.log10(float(total / extent)) / math.log10(period)))


def donchian_vote(candles: Sequence[NormalizedCandle], *, lookback: int = 20) -> int:
    if lookback < 2:
        raise ValueError("Donchian lookback must be at least 2")
    if len(candles) < lookback + 1:
        return 0
    prior = candles[-lookback - 1 : -1]
    latest = candles[-1]
    return (
        1
        if latest.close > max(c.high for c in prior)
        else -1
        if latest.close < min(c.low for c in prior)
        else 0
    )


def supertrend_vote(
    candles: Sequence[NormalizedCandle], *, period: int = 10, multiple: Decimal = Decimal(3)
) -> int:
    if period < 2 or multiple <= 0:
        raise ValueError("invalid Supertrend parameters")
    if len(candles) < period + 1:
        return 0
    true_ranges = [
        max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
        for a, b in pairwise(candles)
    ]
    atr = sum(true_ranges[:period], Decimal(0)) / Decimal(period)
    seed = candles[period]
    midpoint = (seed.high + seed.low) / 2
    upper, lower = midpoint + multiple * atr, midpoint - multiple * atr
    direction = 1 if seed.close >= midpoint else -1
    for index in range(period + 1, len(candles)):
        current, prior = candles[index], candles[index - 1]
        atr = (atr * (period - 1) + true_ranges[index - 1]) / period
        midpoint = (current.high + current.low) / 2
        basic_upper, basic_lower = midpoint + multiple * atr, midpoint - multiple * atr
        upper = basic_upper if basic_upper < upper or prior.close > upper else upper
        lower = basic_lower if basic_lower > lower or prior.close < lower else lower
        if direction < 0 and current.close > upper:
            direction = 1
        elif direction > 0 and current.close < lower:
            direction = -1
    return direction if atr > 0 else 0


def order_block_retest_vote(
    candles: Sequence[NormalizedCandle], *, lookback: int = 13, max_age: int = 21
) -> int:
    """First retest of the last opposite candle before a confirmed range break.

    This is an explicit OHLC proxy, not evidence of institutional orders. A block
    exists only after the breakout closes. Prior touches consume it; a close past
    its far edge invalidates it. Conflicting bullish/bearish retests abstain.
    """
    if lookback < 2 or max_age < 1:
        raise ValueError("invalid order-block parameters")
    if len(candles) < lookback + 2:
        return 0
    latest = candles[-1]
    votes: set[int] = set()
    for index in range(max(lookback, len(candles) - max_age - 1), len(candles) - 1):
        breakout = candles[index]
        prior = candles[index - lookback : index]
        direction = (
            1
            if breakout.close > max(c.high for c in prior)
            else -1
            if breakout.close < min(c.low for c in prior)
            else 0
        )
        if not direction:
            continue
        block = next(
            (
                c
                for c in reversed(prior)
                if (c.close < c.open if direction > 0 else c.close > c.open)
            ),
            None,
        )
        if block is None:
            continue
        intervening = candles[index + 1 : -1]
        if any(c.low <= block.high and c.high >= block.low for c in intervening):
            continue
        if any(
            (c.close < block.low if direction > 0 else c.close > block.high) for c in intervening
        ):
            continue
        touches = latest.low <= block.high and latest.high >= block.low
        reclaimed = (
            (latest.close > block.high and latest.close > latest.open)
            if direction > 0
            else (latest.close < block.low and latest.close < latest.open)
        )
        if touches and reclaimed:
            votes.add(direction)
    return next(iter(votes)) if len(votes) == 1 else 0
