from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from statistics import fmean


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


class Direction(IntEnum):
    SELL = -1
    FLAT = 0
    BUY = 1


TIMEFRAME_WEIGHTS: dict[Timeframe, float] = {
    Timeframe.M1: 0.5,
    Timeframe.M5: 1.0,
    Timeframe.M15: 1.5,
    Timeframe.M30: 1.7,
    Timeframe.H1: 2.3,
    Timeframe.H4: 3.0,
    Timeframe.D1: 3.5,
}


@dataclass(frozen=True, slots=True)
class FrameSignal:
    timeframe: Timeframe
    direction: Direction
    confidence: float
    trend_strength: float
    volatility: float

    def __post_init__(self) -> None:
        for field in ("confidence", "trend_strength", "volatility"):
            value = float(getattr(self, field))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field} must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    direction: Direction
    directional_score: float
    confidence: float
    agreement: float
    execution_alignment: float
    higher_timeframe_alignment: float
    regime: str

    def tradeable(self, *, min_confidence: float = 0.62, min_agreement: float = 0.60) -> bool:
        return (
            self.direction is not Direction.FLAT
            and self.confidence >= min_confidence
            and self.agreement >= min_agreement
            and self.higher_timeframe_alignment >= 0.50
        )


class MultiTimeframeConsensus:
    """Fuse M1..D1 signals without giving this layer order authority."""

    def evaluate(self, signals: list[FrameSignal]) -> ConsensusResult:
        if not signals:
            raise ValueError("at least one timeframe signal is required")
        unique = {signal.timeframe: signal for signal in signals}
        if len(unique) != len(signals):
            raise ValueError("duplicate timeframe signal")

        total_weight = sum(TIMEFRAME_WEIGHTS[s.timeframe] for s in signals)
        raw = sum(
            TIMEFRAME_WEIGHTS[s.timeframe] * float(s.direction) * s.confidence
            for s in signals
        )
        score = raw / total_weight
        if abs(score) < 0.12:
            direction = Direction.FLAT
        else:
            direction = Direction.BUY if score > 0 else Direction.SELL

        aligned_weight = sum(
            TIMEFRAME_WEIGHTS[s.timeframe]
            for s in signals
            if direction is not Direction.FLAT and s.direction is direction
        )
        agreement = aligned_weight / total_weight if direction is not Direction.FLAT else 0.0

        confidence = sum(
            TIMEFRAME_WEIGHTS[s.timeframe] * s.confidence for s in signals
        ) / total_weight

        execution = self._alignment(
            signals,
            direction,
            {Timeframe.M1, Timeframe.M5, Timeframe.M15},
        )
        higher = self._alignment(
            signals,
            direction,
            {Timeframe.H1, Timeframe.H4, Timeframe.D1},
        )
        regime = self._regime(signals)
        return ConsensusResult(
            direction=direction,
            directional_score=score,
            confidence=confidence,
            agreement=agreement,
            execution_alignment=execution,
            higher_timeframe_alignment=higher,
            regime=regime,
        )

    @staticmethod
    def _alignment(
        signals: list[FrameSignal],
        direction: Direction,
        frames: set[Timeframe],
    ) -> float:
        selected = [s for s in signals if s.timeframe in frames]
        if not selected or direction is Direction.FLAT:
            return 0.0
        weights = sum(TIMEFRAME_WEIGHTS[s.timeframe] for s in selected)
        aligned = sum(
            TIMEFRAME_WEIGHTS[s.timeframe] for s in selected if s.direction is direction
        )
        return aligned / weights

    @staticmethod
    def _regime(signals: list[FrameSignal]) -> str:
        trend = fmean(s.trend_strength for s in signals)
        volatility = fmean(s.volatility for s in signals)
        if volatility >= 0.82:
            return "HIGH_VOLATILITY"
        if trend >= 0.65:
            return "TREND"
        if trend <= 0.35 and volatility <= 0.65:
            return "RANGE"
        return "TRANSITION"
