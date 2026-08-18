from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OnlineEventKind(str, Enum):
    MARKET = "market"
    DECISION = "decision"
    OUTCOME = "outcome"
    EXECUTION = "execution"
    INTELLIGENCE = "intelligence"
    REGIME = "regime"


class OutcomeLabel(str, Enum):
    CAPTURED = "captured"
    MISSED = "missed"
    WRONG_DIRECTION = "wrong_direction"
    SAFE_BLOCK = "safe_block"
    NEUTRAL = "neutral"


class OnlineLearningEvent(BaseModel):
    """Small O(1) feedback packet. It has no order/execution authority."""

    model_config = ConfigDict(frozen=True)

    kind: OnlineEventKind
    market: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    regime: str = Field(default="UNKNOWN", min_length=1)
    observed_at: datetime
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    realized_correct: bool | None = None
    outcome: OutcomeLabel | None = None
    prediction_error: float | None = Field(default=None, ge=0.0)
    spread_bps: float | None = Field(default=None, ge=0.0)
    slippage_bps: float | None = Field(default=None, ge=0.0)
    latency_ms: float | None = Field(default=None, ge=0.0)

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("online-learning timestamp must be timezone-aware")
        return value


@dataclass(slots=True, frozen=True)
class OnlineLearningPolicy:
    half_life_events: float = 250.0
    minimum_events_for_research: int = 100
    research_cooldown_events: int = 100
    max_ewma_prediction_error: float = 0.35
    max_ewma_calibration_error: float = 0.20
    max_ewma_missed_rate: float = 0.25
    max_ewma_wrong_direction_rate: float = 0.12
    max_ewma_slippage_bps: float = 20.0

    def __post_init__(self) -> None:
        if self.half_life_events <= 0:
            raise ValueError("half_life_events must be positive")
        if self.minimum_events_for_research <= 0 or self.research_cooldown_events <= 0:
            raise ValueError("research event thresholds must be positive")
        if any(
            value < 0
            for value in (
                self.max_ewma_prediction_error,
                self.max_ewma_calibration_error,
                self.max_ewma_missed_rate,
                self.max_ewma_wrong_direction_rate,
                self.max_ewma_slippage_bps,
            )
        ):
            raise ValueError("online-learning thresholds cannot be negative")

    @property
    def alpha(self) -> float:
        return 1.0 - math.exp(math.log(0.5) / self.half_life_events)


class OnlineLearningSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    market: str
    symbol: str
    regime: str
    events_seen: int
    outcomes_seen: int
    execution_events: int
    ewma_prediction_error: float
    ewma_calibration_error: float
    ewma_missed_rate: float
    ewma_wrong_direction_rate: float
    ewma_capture_rate: float
    ewma_spread_bps: float
    ewma_slippage_bps: float
    ewma_latency_ms: float
    last_observed_at: datetime | None
    last_research_trigger_event: int


class ResearchTrigger(BaseModel):
    model_config = ConfigDict(frozen=True)

    due: bool
    key: str
    reasons: tuple[str, ...]
    events_seen: int
    observed_at: datetime


@dataclass(slots=True)
class _MutableOnlineState:
    market: str
    symbol: str
    regime: str
    events_seen: int = 0
    outcomes_seen: int = 0
    execution_events: int = 0
    prediction_error: float = 0.0
    calibration_error: float = 0.0
    missed_rate: float = 0.0
    wrong_direction_rate: float = 0.0
    capture_rate: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    latency_ms: float = 0.0
    last_observed_at: datetime | None = None
    last_research_trigger_event: int = -1_000_000_000


class SafeOnlineLearner:
    """Continuously learns measurements, never a deployed trading policy.

    `observe` is intentionally O(1) and can be called for every meaningful market,
    decision, fill or outcome event. Threshold breaches produce a research trigger;
    they do not mutate a strategy, change risk limits or call a broker.
    """

    def __init__(self, policy: OnlineLearningPolicy | None = None) -> None:
        self.policy = policy or OnlineLearningPolicy()
        self._states: dict[str, _MutableOnlineState] = {}

    def observe(self, event: OnlineLearningEvent) -> ResearchTrigger:
        key = self.key_for(event.market, event.symbol, event.regime)
        state = self._states.setdefault(
            key,
            _MutableOnlineState(
                market=event.market,
                symbol=event.symbol,
                regime=event.regime,
            ),
        )
        if state.last_observed_at is not None and event.observed_at < state.last_observed_at:
            raise ValueError(f"online-learning event moved backward for {key}")
        state.last_observed_at = event.observed_at
        state.events_seen += 1
        alpha = self.policy.alpha

        if event.prediction_error is not None:
            state.prediction_error = _ewma(state.prediction_error, event.prediction_error, alpha)
        if event.confidence is not None and event.realized_correct is not None:
            target = 1.0 if event.realized_correct else 0.0
            calibration_error = abs(event.confidence - target)
            state.calibration_error = _ewma(
                state.calibration_error,
                calibration_error,
                alpha,
            )
        if event.outcome is not None:
            state.outcomes_seen += 1
            state.missed_rate = _ewma(
                state.missed_rate,
                1.0 if event.outcome == OutcomeLabel.MISSED else 0.0,
                alpha,
            )
            state.wrong_direction_rate = _ewma(
                state.wrong_direction_rate,
                1.0 if event.outcome == OutcomeLabel.WRONG_DIRECTION else 0.0,
                alpha,
            )
            state.capture_rate = _ewma(
                state.capture_rate,
                1.0 if event.outcome == OutcomeLabel.CAPTURED else 0.0,
                alpha,
            )
        if any(value is not None for value in (event.spread_bps, event.slippage_bps, event.latency_ms)):
            state.execution_events += 1
        if event.spread_bps is not None:
            state.spread_bps = _ewma(state.spread_bps, event.spread_bps, alpha)
        if event.slippage_bps is not None:
            state.slippage_bps = _ewma(state.slippage_bps, event.slippage_bps, alpha)
        if event.latency_ms is not None:
            state.latency_ms = _ewma(state.latency_ms, event.latency_ms, alpha)

        reasons = self._research_reasons(state)
        cooldown_satisfied = (
            state.events_seen - state.last_research_trigger_event
            >= self.policy.research_cooldown_events
        )
        due = bool(reasons) and cooldown_satisfied
        if due:
            state.last_research_trigger_event = state.events_seen
        return ResearchTrigger(
            due=due,
            key=key,
            reasons=tuple(reasons) if due else (),
            events_seen=state.events_seen,
            observed_at=event.observed_at,
        )

    def snapshot(self, *, market: str, symbol: str, regime: str = "UNKNOWN") -> OnlineLearningSnapshot:
        key = self.key_for(market, symbol, regime)
        state = self._states.get(key)
        if state is None:
            return OnlineLearningSnapshot(
                market=market,
                symbol=symbol,
                regime=regime,
                events_seen=0,
                outcomes_seen=0,
                execution_events=0,
                ewma_prediction_error=0.0,
                ewma_calibration_error=0.0,
                ewma_missed_rate=0.0,
                ewma_wrong_direction_rate=0.0,
                ewma_capture_rate=0.0,
                ewma_spread_bps=0.0,
                ewma_slippage_bps=0.0,
                ewma_latency_ms=0.0,
                last_observed_at=None,
                last_research_trigger_event=-1_000_000_000,
            )
        return self._snapshot(state)

    def snapshots(self) -> tuple[OnlineLearningSnapshot, ...]:
        return tuple(self._snapshot(self._states[key]) for key in sorted(self._states))

    @staticmethod
    def key_for(market: str, symbol: str, regime: str) -> str:
        return f"{market.upper()}::{symbol.upper()}::{regime.upper()}"

    def _research_reasons(self, state: _MutableOnlineState) -> list[str]:
        if state.events_seen < self.policy.minimum_events_for_research:
            return []
        reasons: list[str] = []
        checks = (
            (
                state.prediction_error,
                self.policy.max_ewma_prediction_error,
                "prediction_error",
            ),
            (
                state.calibration_error,
                self.policy.max_ewma_calibration_error,
                "calibration_error",
            ),
            (state.missed_rate, self.policy.max_ewma_missed_rate, "missed_rate"),
            (
                state.wrong_direction_rate,
                self.policy.max_ewma_wrong_direction_rate,
                "wrong_direction_rate",
            ),
            (state.slippage_bps, self.policy.max_ewma_slippage_bps, "slippage_bps"),
        )
        for actual, limit, name in checks:
            if actual > limit:
                reasons.append(f"{name}={actual:.6f}>{limit:.6f}")
        return reasons

    @staticmethod
    def _snapshot(state: _MutableOnlineState) -> OnlineLearningSnapshot:
        return OnlineLearningSnapshot(
            market=state.market,
            symbol=state.symbol,
            regime=state.regime,
            events_seen=state.events_seen,
            outcomes_seen=state.outcomes_seen,
            execution_events=state.execution_events,
            ewma_prediction_error=state.prediction_error,
            ewma_calibration_error=state.calibration_error,
            ewma_missed_rate=state.missed_rate,
            ewma_wrong_direction_rate=state.wrong_direction_rate,
            ewma_capture_rate=state.capture_rate,
            ewma_spread_bps=state.spread_bps,
            ewma_slippage_bps=state.slippage_bps,
            ewma_latency_ms=state.latency_ms,
            last_observed_at=state.last_observed_at,
            last_research_trigger_event=state.last_research_trigger_event,
        )


def _ewma(previous: float, value: float, alpha: float) -> float:
    return previous + alpha * (value - previous)
