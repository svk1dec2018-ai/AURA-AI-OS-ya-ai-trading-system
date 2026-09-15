from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict

from aura.domain.models import NormalizedCandle


class DataQualitySeverity(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class DataQualityIssueType(str, Enum):
    EMPTY_SERIES = "empty_series"
    MIXED_SYMBOLS = "mixed_symbols"
    MIXED_TIMEFRAMES = "mixed_timeframes"
    OPEN_CANDLE = "open_candle"
    DUPLICATE_BAR = "duplicate_bar"
    OUT_OF_ORDER = "out_of_order"
    GAP = "gap"
    STALE = "stale"
    FUTURE_DATA = "future_data"


class DataQualityIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    issue_type: DataQualityIssueType
    severity: DataQualitySeverity
    detail: str


@dataclass(slots=True, frozen=True)
class DataQualityPolicy:
    expected_interval: timedelta
    max_staleness: timedelta
    max_gap_multiple: int = 2

    def __post_init__(self) -> None:
        if self.expected_interval <= timedelta(0):
            raise ValueError("expected_interval must be positive")
        if self.max_staleness < timedelta(0):
            raise ValueError("max_staleness cannot be negative")
        if self.max_gap_multiple < 1:
            raise ValueError("max_gap_multiple must be at least 1")


@dataclass(slots=True, frozen=True)
class DataQualityReport:
    issues: tuple[DataQualityIssue, ...]
    bars_checked: int
    latest_data_lag_ms: int | None

    @property
    def safe_for_decision(self) -> bool:
        return not any(issue.severity == DataQualitySeverity.CRITICAL for issue in self.issues)


class CandleQualityGate:
    """Point-in-time candle validation before strategy or agent decisions."""

    def __init__(self, policy: DataQualityPolicy) -> None:
        self.policy = policy

    def assess(
        self,
        candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle],
        *,
        decision_time: datetime,
    ) -> DataQualityReport:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")

        issues: list[DataQualityIssue] = []
        if not candles:
            issues.append(
                DataQualityIssue(
                    issue_type=DataQualityIssueType.EMPTY_SERIES,
                    severity=DataQualitySeverity.CRITICAL,
                    detail="no candles are available for the decision",
                )
            )
            return DataQualityReport(
                issues=tuple(issues),
                bars_checked=0,
                latest_data_lag_ms=None,
            )

        if len({candle.symbol for candle in candles}) != 1:
            issues.append(
                DataQualityIssue(
                    issue_type=DataQualityIssueType.MIXED_SYMBOLS,
                    severity=DataQualitySeverity.CRITICAL,
                    detail="decision series contains multiple symbols",
                )
            )
        if len({candle.timeframe for candle in candles}) != 1:
            issues.append(
                DataQualityIssue(
                    issue_type=DataQualityIssueType.MIXED_TIMEFRAMES,
                    severity=DataQualitySeverity.CRITICAL,
                    detail="decision series contains multiple timeframes",
                )
            )
        if any(not candle.closed for candle in candles):
            issues.append(
                DataQualityIssue(
                    issue_type=DataQualityIssueType.OPEN_CANDLE,
                    severity=DataQualitySeverity.CRITICAL,
                    detail="open/incomplete candle entered the decision series",
                )
            )

        seen: set[tuple[datetime, datetime]] = set()
        previous: NormalizedCandle | None = None
        max_allowed_gap = self.policy.expected_interval * self.policy.max_gap_multiple
        for candle in candles:
            key = (candle.open_time, candle.close_time)
            if key in seen:
                issues.append(
                    DataQualityIssue(
                        issue_type=DataQualityIssueType.DUPLICATE_BAR,
                        severity=DataQualitySeverity.CRITICAL,
                        detail=f"duplicate candle beginning {candle.open_time.isoformat()}",
                    )
                )
            seen.add(key)

            if candle.close_time > decision_time:
                issues.append(
                    DataQualityIssue(
                        issue_type=DataQualityIssueType.FUTURE_DATA,
                        severity=DataQualitySeverity.CRITICAL,
                        detail=(
                            f"candle closes at {candle.close_time.isoformat()} after decision time "
                            f"{decision_time.isoformat()}"
                        ),
                    )
                )

            if previous is not None:
                if candle.open_time <= previous.open_time:
                    issues.append(
                        DataQualityIssue(
                            issue_type=DataQualityIssueType.OUT_OF_ORDER,
                            severity=DataQualitySeverity.CRITICAL,
                            detail=(
                                f"bar order is not strictly increasing at "
                                f"{candle.open_time.isoformat()}"
                            ),
                        )
                    )
                gap = candle.open_time - previous.open_time
                if gap > max_allowed_gap:
                    issues.append(
                        DataQualityIssue(
                            issue_type=DataQualityIssueType.GAP,
                            severity=DataQualitySeverity.CRITICAL,
                            detail=(
                                f"observed bar gap {gap} exceeds allowed "
                                f"{max_allowed_gap}"
                            ),
                        )
                    )
            previous = candle

        last = candles[-1]
        staleness = decision_time - last.close_time
        if staleness > self.policy.max_staleness:
            issues.append(
                DataQualityIssue(
                    issue_type=DataQualityIssueType.STALE,
                    severity=DataQualitySeverity.CRITICAL,
                    detail=(
                        f"last closed candle is stale by {staleness}; "
                        f"allowed {self.policy.max_staleness}"
                    ),
                )
            )

        latest_data_lag_ms = max(
            0,
            int((decision_time - last.close_time).total_seconds() * 1000),
        )
        return DataQualityReport(
            issues=tuple(issues),
            bars_checked=len(candles),
            latest_data_lag_ms=latest_data_lag_ms,
        )
