from datetime import UTC, datetime, time
from decimal import Decimal

from aura.data.candle_aggregation import (
    CandleSession,
    CanonicalTradeTick,
    SessionCandleAggregator,
)


def _tick(hour: int, minute: int, second: int, price: str, quantity: str = "1"):
    return CanonicalTradeTick(
        symbol="NIFTY",
        venue="DHAN",
        price=Decimal(price),
        quantity=Decimal(quantity),
        timestamp=datetime(2026, 8, 17, hour, minute, second, tzinfo=UTC),
    )


def test_india_session_5m_buckets_anchor_from_0915_ist() -> None:
    aggregator = SessionCandleAggregator(
        timeframes=("5m",),
        session=CandleSession(timezone="Asia/Kolkata", session_start=time(9, 15)),
    )
    # 03:45 UTC = 09:15 IST.
    assert aggregator.on_tick(_tick(3, 45, 5, "100")) == ()
    assert aggregator.on_tick(_tick(3, 47, 0, "102", "2")) == ()
    completed = aggregator.on_tick(_tick(3, 50, 1, "101"))
    assert len(completed) == 1
    candle = completed[0]
    assert candle.open_time == datetime(2026, 8, 17, 3, 45, tzinfo=UTC)
    assert candle.close_time == datetime(2026, 8, 17, 3, 50, tzinfo=UTC)
    assert candle.open == Decimal(100)
    assert candle.high == Decimal(102)
    assert candle.low == Decimal(100)
    assert candle.close == Decimal(102)
    assert candle.volume == Decimal(3)


def test_flush_closes_existing_bucket_without_fabricating_gap_bars() -> None:
    aggregator = SessionCandleAggregator(timeframes=("1m",))
    aggregator.on_tick(_tick(10, 0, 10, "200", "4"))
    completed = aggregator.flush_until(datetime(2026, 8, 17, 10, 1, tzinfo=UTC))
    assert len(completed) == 1
    assert completed[0].volume == Decimal(4)
    assert aggregator.flush_until(datetime(2026, 8, 17, 10, 5, tzinfo=UTC)) == ()
