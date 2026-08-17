from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.data.quality import CandleQualityGate, DataQualityIssueType, DataQualityPolicy
from aura.domain.models import NormalizedCandle


def _bar(minute: int) -> NormalizedCandle:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    return NormalizedCandle(
        symbol="X",
        venue="TEST",
        timeframe="1m",
        open_time=start,
        close_time=start + timedelta(minutes=1),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(10),
        closed=True,
    )


def _gate() -> CandleQualityGate:
    return CandleQualityGate(
        DataQualityPolicy(
            expected_interval=timedelta(minutes=1),
            max_staleness=timedelta(minutes=2),
            max_gap_multiple=2,
        )
    )


def test_clean_series_is_safe() -> None:
    bars = [_bar(0), _bar(1), _bar(2)]
    report = _gate().assess(
        bars,
        decision_time=datetime(2026, 1, 1, 0, 3, 30, tzinfo=UTC),
    )
    assert report.safe_for_decision
    assert report.issues == ()


def test_duplicate_and_out_of_order_bars_are_blocked() -> None:
    report = _gate().assess(
        [_bar(0), _bar(1), _bar(1)],
        decision_time=datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
    )
    issue_types = {issue.issue_type for issue in report.issues}
    assert DataQualityIssueType.DUPLICATE_BAR in issue_types
    assert DataQualityIssueType.OUT_OF_ORDER in issue_types
    assert not report.safe_for_decision


def test_gap_and_staleness_are_blocked() -> None:
    report = _gate().assess(
        [_bar(0), _bar(5)],
        decision_time=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
    )
    issue_types = {issue.issue_type for issue in report.issues}
    assert DataQualityIssueType.GAP in issue_types
    assert DataQualityIssueType.STALE in issue_types
    assert not report.safe_for_decision


def test_future_bar_is_blocked() -> None:
    report = _gate().assess(
        [_bar(0), _bar(1)],
        decision_time=datetime(2026, 1, 1, 0, 1, 30, tzinfo=UTC),
    )
    assert any(issue.issue_type == DataQualityIssueType.FUTURE_DATA for issue in report.issues)
    assert not report.safe_for_decision
