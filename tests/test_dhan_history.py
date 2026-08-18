from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aura.data.dhan_history import DhanHistoricalDataError, normalize_dhan_intraday_response
from aura.markets.universe import AssetClass, CanonicalInstrument, VenueFamily


def _instrument() -> CanonicalInstrument:
    return CanonicalInstrument(
        instrument_id="dhan:NSE_EQ:1333",
        canonical_symbol="HDFCBANK",
        venue_family=VenueFamily.DHAN_INDIA,
        venue_symbol="1333",
        asset_class=AssetClass.CASH_EQUITY,
        exchange="NSE",
        segment="NSE_EQ",
        currency="INR",
        tick_size=Decimal("0.05"),
        min_quantity=Decimal(1),
        quantity_step=Decimal(1),
    )


def test_dhan_history_normalizer_excludes_not_yet_closed_bar() -> None:
    first = 1_700_000_000
    payload = {
        "open": [100, 101],
        "high": [102, 103],
        "low": [99, 100],
        "close": [101, 102],
        "volume": [1000, 1200],
        "timestamp": [first, first + 60],
    }
    as_of = datetime.fromtimestamp(first + 90, tz=UTC)
    candles = normalize_dhan_intraday_response(
        payload,
        instrument=_instrument(),
        interval_minutes=1,
        as_of=as_of,
    )
    assert len(candles) == 1
    assert candles[0].close == Decimal(101)
    assert candles[0].closed
    assert candles[0].venue == "DHAN_LIVE"


def test_dhan_history_normalizer_fails_on_inconsistent_arrays() -> None:
    payload = {
        "open": [100],
        "high": [101],
        "low": [99],
        "close": [100],
        "volume": [],
        "timestamp": [1_700_000_000],
    }
    with pytest.raises(DhanHistoricalDataError, match="inconsistent"):
        normalize_dhan_intraday_response(
            payload,
            instrument=_instrument(),
            interval_minutes=1,
            as_of=datetime(2026, 8, 18, tzinfo=UTC),
        )
