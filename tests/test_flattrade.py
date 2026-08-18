from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.data.flattrade import (
    FlattradeSubscription,
    FlattradeTouchlineNormalizer,
    normalize_flattrade_time_price_series,
)


def test_flattrade_touchline_merges_delta_volume() -> None:
    normalizer = FlattradeTouchlineNormalizer(
        (FlattradeSubscription(exchange="NSE", token="22", symbol="SBIN"),)
    )
    now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    first = normalizer.normalize(
        {"t": "tk", "e": "NSE", "tk": "22", "lp": "1156.50", "v": "819881"},
        received_at=now,
    )
    assert first is not None
    assert first.price == Decimal("1156.50")
    assert first.quantity == Decimal(0)

    second = normalizer.normalize(
        {"t": "tf", "e": "NSE", "tk": "22", "v": "820001"},
        received_at=now + timedelta(seconds=1),
    )
    assert second is not None
    assert second.price == Decimal("1156.50")
    assert second.quantity == Decimal(120)


def test_flattrade_tpseries_excludes_forming_candle() -> None:
    rows = [
        {
            "time": "18/08/2026 09:15:00",
            "into": "100",
            "inth": "102",
            "intl": "99",
            "intc": "101",
            "intv": "500",
        },
        {
            "time": "18/08/2026 09:16:00",
            "into": "101",
            "inth": "103",
            "intl": "100",
            "intc": "102",
            "intv": "600",
        },
    ]
    as_of = datetime(2026, 8, 18, 3, 46, 30, tzinfo=UTC)
    candles = normalize_flattrade_time_price_series(
        rows,
        symbol="SBIN",
        interval_minutes=1,
        as_of=as_of,
    )
    assert len(candles) == 1
    assert candles[0].close == Decimal(101)
    assert candles[0].venue == "FLATTRADE_LIVE"
