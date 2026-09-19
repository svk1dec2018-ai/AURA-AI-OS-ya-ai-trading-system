from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from itertools import pairwise

from aura.domain.models import NormalizedCandle, SignalIntent, StrategySignal
from aura.evolution.core import (
    CandidateEvaluation,
    FitnessPolicy,
    GeneKind,
    GeneSpec,
    StrategyGenome,
)
from aura.strategy.base import Strategy
from aura.strategy.ema import _ema


class StrategyStyle(str, Enum):
    HYBRID = "hybrid"
    TREND = "trend"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"


_FEATURE_NAMES = (
    "ema",
    "rsi",
    "momentum",
    "breakout",
    "bollinger",
    "volume",
    "atr",
)


def autonomous_strategy_gene_specs() -> tuple[GeneSpec, ...]:
    """Bounded search grammar for AI-created trading hypotheses.

    The lab can explore a large combinatorial strategy space, but cannot generate
    arbitrary executable code or mutate RiskEngine controls.
    """

    genes: list[GeneSpec] = [
        GeneSpec(
            name="style",
            kind=GeneKind.CATEGORICAL,
            choices=tuple(item.value for item in StrategyStyle),
        ),
        GeneSpec(name="fast_ema", kind=GeneKind.INTEGER, low=4, high=40, step=1),
        GeneSpec(name="slow_ema", kind=GeneKind.INTEGER, low=18, high=240, step=1),
        GeneSpec(name="rsi_period", kind=GeneKind.INTEGER, low=5, high=35, step=1),
        GeneSpec(name="momentum_lookback", kind=GeneKind.INTEGER, low=2, high=40, step=1),
        GeneSpec(name="breakout_lookback", kind=GeneKind.INTEGER, low=5, high=120, step=1),
        GeneSpec(name="band_lookback", kind=GeneKind.INTEGER, low=10, high=100, step=1),
        GeneSpec(name="volume_lookback", kind=GeneKind.INTEGER, low=5, high=80, step=1),
        GeneSpec(name="atr_lookback", kind=GeneKind.INTEGER, low=5, high=80, step=1),
        GeneSpec(name="min_votes", kind=GeneKind.INTEGER, low=1, high=6, step=1),
        GeneSpec(name="rsi_long", kind=GeneKind.FLOAT, low=48, high=68, step=1),
        GeneSpec(name="rsi_short", kind=GeneKind.FLOAT, low=32, high=52, step=1),
        GeneSpec(name="volume_ratio", kind=GeneKind.FLOAT, low=1.0, high=3.0, step=0.1),
        GeneSpec(name="atr_ratio", kind=GeneKind.FLOAT, low=0.8, high=2.5, step=0.1),
        GeneSpec(name="band_z", kind=GeneKind.FLOAT, low=0.7, high=2.5, step=0.1),
    ]
    genes.extend(
        GeneSpec(
            name=f"use_{name}",
            kind=GeneKind.CATEGORICAL,
            choices=("off", "on"),
        )
        for name in _FEATURE_NAMES
    )
    return tuple(genes)


@dataclass(slots=True, frozen=True)
class AutonomousStrategyBlueprint:
    style: StrategyStyle
    fast_ema: int
    slow_ema: int
    rsi_period: int
    momentum_lookback: int
    breakout_lookback: int
    band_lookback: int
    volume_lookback: int
    atr_lookback: int
    min_votes: int
    rsi_long: float
    rsi_short: float
    volume_ratio: float
    atr_ratio: float
    band_z: float
    enabled_features: frozenset[str]

    @classmethod
    def from_genome(cls, genome: StrategyGenome) -> AutonomousStrategyBlueprint:
        if genome.family != "autonomous_strategy_dsl.v1":
            raise ValueError("unsupported autonomous strategy genome family")
        p = genome.parameters
        fast = int(p["fast_ema"])
        slow = max(int(p["slow_ema"]), fast + 2)
        features = frozenset(
            name for name in _FEATURE_NAMES if str(p.get(f"use_{name}", "off")) == "on"
        )
        if not features:
            features = frozenset({"ema", "momentum"})
        min_votes = min(max(int(p["min_votes"]), 1), len(features))
        rsi_long = float(p["rsi_long"])
        rsi_short = min(float(p["rsi_short"]), rsi_long - 1.0)
        return cls(
            style=StrategyStyle(str(p["style"])),
            fast_ema=fast,
            slow_ema=slow,
            rsi_period=int(p["rsi_period"]),
            momentum_lookback=int(p["momentum_lookback"]),
            breakout_lookback=int(p["breakout_lookback"]),
            band_lookback=int(p["band_lookback"]),
            volume_lookback=int(p["volume_lookback"]),
            atr_lookback=int(p["atr_lookback"]),
            min_votes=min_votes,
            rsi_long=rsi_long,
            rsi_short=rsi_short,
            volume_ratio=float(p["volume_ratio"]),
            atr_ratio=float(p["atr_ratio"]),
            band_z=float(p["band_z"]),
            enabled_features=features,
        )

    @property
    def warmup_bars(self) -> int:
        return max(
            self.slow_ema + 2,
            self.rsi_period + 2,
            self.momentum_lookback + 2,
            self.breakout_lookback + 2,
            self.band_lookback + 2,
            self.volume_lookback + 2,
            self.atr_lookback + 2,
        )


class AutonomousDslStrategy(Strategy):
    """Compiled safe strategy created from an immutable AI-search genome.

    This strategy deliberately exposes no risk-sizing genes. It produces only an
    alpha intent/confidence; AURA's independent RiskEngine retains all authority.
    """

    def __init__(self, genome: StrategyGenome) -> None:
        self.genome = genome
        self.blueprint = AutonomousStrategyBlueprint.from_genome(genome)
        self.strategy_id = f"research.{genome.genome_id}"
        self.warmup_bars = self.blueprint.warmup_bars

    def on_closed_candle(self, history: Sequence[NormalizedCandle]) -> StrategySignal | None:
        if len(history) < self.warmup_bars:
            return None
        relevant = history[-self.warmup_bars :]
        if not all(item.closed for item in relevant):
            return None
        latest = history[-1]
        if any(item.symbol != latest.symbol or item.timeframe != latest.timeframe for item in relevant):
            return None

        votes = self._votes(history)
        long_votes = sum(1 for value in votes.values() if value > 0)
        short_votes = sum(1 for value in votes.values() if value < 0)
        required = min(self.blueprint.min_votes, max(len(votes), 1))
        if long_votes >= required and long_votes > short_votes:
            intent = SignalIntent.LONG
            directional = long_votes
        elif short_votes >= required and short_votes > long_votes:
            intent = SignalIntent.SHORT
            directional = short_votes
        else:
            return None

        enabled_count = max(len(votes), 1)
        margin = abs(long_votes - short_votes) / enabled_count
        coverage = directional / enabled_count
        confidence = min(0.99, 0.45 + 0.30 * coverage + 0.24 * margin)
        reason = (
            f"autonomous-dsl style={self.blueprint.style.value} "
            f"votes=L{long_votes}/S{short_votes}; "
            + ",".join(f"{name}:{value:+d}" for name, value in sorted(votes.items()))
        )
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=latest.symbol,
            intent=intent,
            confidence=confidence,
            reference_price=latest.close,
            generated_at=latest.close_time,
            reason=reason,
        )

    def _votes(self, history: Sequence[NormalizedCandle]) -> dict[str, int]:
        b = self.blueprint
        votes: dict[str, int] = {}
        closes = [item.close for item in history]
        latest = history[-1]

        if "ema" in b.enabled_features:
            fast = _ema(closes, b.fast_ema)
            slow = _ema(closes, b.slow_ema)
            votes["ema"] = _sign(fast - slow)

        if "rsi" in b.enabled_features:
            rsi = _rsi(closes, b.rsi_period)
            votes["rsi"] = 1 if rsi >= b.rsi_long else -1 if rsi <= b.rsi_short else 0

        if "momentum" in b.enabled_features:
            anchor = history[-1 - b.momentum_lookback].close
            votes["momentum"] = _sign(latest.close - anchor)

        if "breakout" in b.enabled_features:
            prior = history[-1 - b.breakout_lookback : -1]
            prior_high = max(item.high for item in prior)
            prior_low = min(item.low for item in prior)
            votes["breakout"] = 1 if latest.close > prior_high else -1 if latest.close < prior_low else 0

        if "bollinger" in b.enabled_features:
            window = closes[-b.band_lookback :]
            mean = sum(window, Decimal(0)) / Decimal(len(window))
            variance = sum((value - mean) ** 2 for value in window) / Decimal(len(window))
            stdev = variance.sqrt() if variance > 0 else Decimal(0)
            if stdev == 0:
                band_vote = 0
            else:
                z = float((latest.close - mean) / stdev)
                if b.style == StrategyStyle.MEAN_REVERSION:
                    band_vote = -1 if z >= b.band_z else 1 if z <= -b.band_z else 0
                else:
                    band_vote = 1 if z >= b.band_z else -1 if z <= -b.band_z else 0
            votes["bollinger"] = band_vote

        if "volume" in b.enabled_features:
            prior_volume = [item.volume for item in history[-1 - b.volume_lookback : -1]]
            avg_volume = sum(prior_volume, Decimal(0)) / Decimal(len(prior_volume))
            if avg_volume <= 0 or latest.volume < avg_volume * Decimal(str(b.volume_ratio)):
                votes["volume"] = 0
            else:
                votes["volume"] = _sign(latest.close - latest.open)

        if "atr" in b.enabled_features:
            atr_now = _atr(history[-b.atr_lookback :])
            prior_window = history[-1 - b.atr_lookback : -1]
            atr_prior = _atr(prior_window)
            if atr_prior <= 0 or atr_now < atr_prior * Decimal(str(b.atr_ratio)):
                votes["atr"] = 0
            else:
                votes["atr"] = _sign(latest.close - latest.open)

        return _style_filter(votes, b.style)


def strategy_from_autonomous_genome(genome: StrategyGenome) -> Strategy:
    return AutonomousDslStrategy(genome)


def _style_filter(votes: dict[str, int], style: StrategyStyle) -> dict[str, int]:
    if style == StrategyStyle.HYBRID:
        return votes
    preferred = {
        StrategyStyle.TREND: {"ema", "rsi", "momentum", "volume", "atr"},
        StrategyStyle.BREAKOUT: {"ema", "momentum", "breakout", "volume", "atr"},
        StrategyStyle.MEAN_REVERSION: {"rsi", "bollinger", "volume", "atr"},
    }[style]
    filtered = {name: value for name, value in votes.items() if name in preferred}
    return filtered or votes


def _sign(value: Decimal) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _rsi(values: Sequence[Decimal], period: int) -> float:
    window = values[-(period + 1) :]
    gains = Decimal(0)
    losses = Decimal(0)
    for prior, current in pairwise(window):
        change = current - prior
        if change > 0:
            gains += change
        elif change < 0:
            losses -= change
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return float(Decimal(100) - Decimal(100) / (Decimal(1) + rs))


def _atr(candles: Sequence[NormalizedCandle]) -> Decimal:
    if len(candles) < 2:
        return Decimal(0)
    values: list[Decimal] = []
    for prior, current in pairwise(candles):
        values.append(
            max(
                current.high - current.low,
                abs(current.high - prior.close),
                abs(current.low - prior.close),
            )
        )
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else Decimal(0)


@dataclass(slots=True, frozen=True)
class ProTraderResearchObjective:
    """Reward high accuracy without allowing win-rate gaming or tiny samples."""

    aspirational_win_rate: float = 0.80
    min_oos_trades_for_confidence: int = 200
    minimum_profit_factor: float = 1.10
    maximum_drawdown_pct: float = 15.0
    base_policy: FitnessPolicy = field(default_factory=FitnessPolicy)

    def __post_init__(self) -> None:
        if not 0 < self.aspirational_win_rate < 1:
            raise ValueError("aspirational_win_rate must be in (0, 1)")
        if self.min_oos_trades_for_confidence <= 0:
            raise ValueError("minimum OOS trades must be positive")

    def score(self, evaluation: CandidateEvaluation) -> float:
        base = self.base_policy.score(evaluation)
        folds = evaluation.walk_forward or (evaluation.in_sample,)
        weighted_trades = sum(item.trades for item in folds)
        if weighted_trades:
            win_rate = sum(item.win_rate * item.trades for item in folds) / weighted_trades
            expectancy = sum(item.expectancy_pct * item.trades for item in folds) / weighted_trades
        else:
            win_rate = 0.0
            expectancy = 0.0
        sample_strength = min(
            1.0,
            math.log1p(weighted_trades) / math.log1p(self.min_oos_trades_for_confidence),
        )
        accuracy_progress = min(win_rate / self.aspirational_win_rate, 1.0)
        accuracy_bonus = 3.0 * accuracy_progress * sample_strength
        low_sample_penalty = 3.0 * (1.0 - sample_strength)
        expectancy_penalty = 4.0 if expectancy <= 0 else 0.0
        return base + accuracy_bonus - low_sample_penalty - expectancy_penalty

    def research_failures(self, evaluation: CandidateEvaluation) -> tuple[str, ...]:
        failures = list(self.base_policy.research_failures(evaluation))
        if evaluation.total_oos_trades < self.min_oos_trades_for_confidence:
            failures.append("pro_trader_sample_too_small")
        folds = evaluation.walk_forward
        if folds and min(item.profit_factor for item in folds) < self.minimum_profit_factor:
            failures.append("pro_trader_profit_factor")
        if folds and max(item.max_drawdown_pct for item in folds) > self.maximum_drawdown_pct:
            failures.append("pro_trader_drawdown")
        return tuple(dict.fromkeys(failures))
