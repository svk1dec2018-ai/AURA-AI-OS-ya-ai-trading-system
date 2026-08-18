from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.data.shoonya import (
    ShoonyaSubscription,
    ShoonyaTouchlineNormalizer,
    normalize_shoonya_time_price_series,
)


def test_shoonya_touchline_merges_delta_packets_and_volume() -> None:
    normalizer = ShoonyaTouchlineNormalizer(
        (ShoonyaSubscription(exchange="NSE", token="11630", symbol="NTPC"),)
    )
    now = datetime(2026, 8, 18, 3, 45, tzinfo=UTC)
    first = normalizer.normalize(
        {"t": "tk", "e": "NSE", "tk": "11630", "lp": "118.55", "v": "162220"},
        received_at=now,
    )
    assert first is not None
    assert first.price == Decimal("118.55")
    assert first.quantity == Decimal(0)

    second = normalizer.normalize(
        {"t": "tf", "e": "NSE", "tk": "11630", "v": "166637"},
        received_at=now + timedelta(seconds=1),
    )
    assert second is not None
    assert second.price == Decimal("118.55")
    assert second.quantity == Decimal(4417)


def test_shoonya_time_price_series_is_point_in_time_safe() -> None:
    first = 1_776_000_000
    rows = [
        {
            "ssboe": str(first),
            "into": "100",
            "inth": "102",
            "intl": "99",
            "intc": "101",
            "intv": "1000",
        },
        {
            "ssboe": str(first + 60),
            "into": "101",
            "inth": "103",
            "intl": "100",
            "intc": "102",
            "intv": "1200",
        },
    ]
    candles = normalize_shoonya_time_price_series(
        rows,
        symbol="RELIANCE",
        interval_minutes=1,
        as_of=datetime.fromtimestamp(first + 90, tz=UTC),
    )
    assert len(candles) == 1
    assert candles[0].close == Decimal(101)
    assert candles[0].venue == "SHOONYA_LIVE"
