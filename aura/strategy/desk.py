"""Bounded multi-strategy advisory desk, with one vote per hypothesis family."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aura.domain.models import NormalizedCandle, SignalIntent
from aura.research.blueprint_compiler import compile_blueprint
from aura.research.strategy_catalog import STRATEGY_SETUPS
from aura.strategy.causal_indicators import choppiness


@dataclass(frozen=True, slots=True)
class StrategyDeskDecision:
    intent: SignalIntent
    agreement: float
    regime: str
    active_setups: tuple[str, ...]
    supporting_families: tuple[str, ...]
    conflicting_families: tuple[str, ...]
    reason: str
    research_only: bool = True
    execution_authority: bool = False


class CausalStrategyDesk:
    def __init__(self) -> None:
        self.strategies = tuple(
            (setup, compile_blueprint(setup.blueprint())) for setup in STRATEGY_SETUPS
        )

    def evaluate(self, history: Sequence[NormalizedCandle]) -> StrategyDeskDecision:
        chop = choppiness(history)
        regime = (
            "unknown"
            if chop is None
            else "range"
            if chop >= 61.8
            else "trend"
            if chop <= 38.2
            else "transition"
        )
        families: dict[str, set[SignalIntent]] = {}
        active: list[str] = []
        for setup, strategy in self.strategies:
            signal = strategy.on_closed_candle(history)
            if signal is None or signal.intent == SignalIntent.FLAT:
                continue
            active.append(setup.key)
            families.setdefault(setup.family, set()).add(signal.intent)
        longs = sorted(key for key, votes in families.items() if votes == {SignalIntent.LONG})
        shorts = sorted(key for key, votes in families.items() if votes == {SignalIntent.SHORT})
        conflicts = sorted(key for key, votes in families.items() if len(votes) > 1)
        winner, opposite = (longs, shorts) if len(longs) > len(shorts) else (shorts, longs)
        agreement = len(winner) / len(families) if families else 0.0
        intent = SignalIntent.LONG if len(longs) > len(shorts) else SignalIntent.SHORT
        if len(winner) < 2 or len(winner) <= len(opposite) or agreement < 0.60:
            intent = SignalIntent.FLAT
        return StrategyDeskDecision(
            intent=intent,
            agreement=agreement,
            regime=regime,
            active_setups=tuple(active),
            supporting_families=tuple(winner),
            conflicting_families=tuple(sorted(set(opposite + conflicts))),
            reason=f"{len(active)} active setups; long families={longs}; short families={shorts}; conflicts={conflicts}; require >=2 families and >=60% agreement",
        )
