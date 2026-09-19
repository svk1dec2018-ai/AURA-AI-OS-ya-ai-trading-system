from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aura.markets.universe import (
    AssetClass,
    CanonicalInstrument,
    OptionType,
    UniversalMarketUniverse,
    VenueFamily,
)


def _instrument(**overrides):
    values = {
        "instrument_id": "exness:XAUUSD",
        "canonical_symbol": "XAUUSD",
        "venue_family": VenueFamily.EXNESS_MT5,
        "venue_symbol": "XAUUSD",
        "asset_class": AssetClass.METAL,
        "currency": "USD",
        "tick_size": Decimal("0.01"),
        "min_quantity": Decimal("0.01"),
        "quantity_step": Decimal("0.01"),
    }
    values.update(overrides)
    return CanonicalInstrument(**values)


def test_exness_and_indian_derivatives_coexist_in_one_canonical_universe() -> None:
    universe = UniversalMarketUniverse()
    universe.upsert(_instrument())
    universe.upsert(
        _instrument(
            instrument_id="dhan:NFO:NIFTY:20260827:25000:CE",
            canonical_symbol="NIFTY-20260827-25000-CE",
            venue_family=VenueFamily.DHAN_INDIA,
            venue_symbol="123456",
            asset_class=AssetClass.OPTION,
            exchange="NSE",
            segment="NFO",
            currency="INR",
            underlying="NIFTY",
            expiry=datetime(2026, 8, 27, 15, 30, tzinfo=UTC),
            strike=Decimal(25000),
            option_type=OptionType.CALL,
            lot_size=Decimal(75),
            tick_size=Decimal("0.05"),
            min_quantity=Decimal(75),
            quantity_step=Decimal(75),
        )
    )

    assert len(universe.eligible()) == 2
    assert {item.venue_family for item in universe.eligible()} == {
        VenueFamily.EXNESS_MT5,
        VenueFamily.DHAN_INDIA,
    }


def test_scan_plan_expands_every_eligible_instrument_across_all_timeframes() -> None:
    universe = UniversalMarketUniverse()
    universe.upsert(_instrument())
    plan = universe.scan_plan()

    assert len(plan) == 7
    assert {timeframe for _, timeframe in plan} == {
        "1m",
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "1d",
    }


def test_non_tradable_or_data_disabled_symbols_do_not_enter_scan_plan() -> None:
    universe = UniversalMarketUniverse()
    universe.upsert(_instrument(tradable=False))
    universe.upsert(
        _instrument(
            instrument_id="exness:EURUSD",
            canonical_symbol="EURUSD",
            venue_symbol="EURUSD",
            asset_class=AssetClass.FOREX,
            market_data_enabled=False,
        )
    )
    assert universe.scan_plan() == ()


def test_option_requires_underlying_expiry_strike_and_side() -> None:
    with pytest.raises(ValueError, match="option instrument missing fields"):
        _instrument(
            instrument_id="bad-option",
            asset_class=AssetClass.OPTION,
            venue_family=VenueFamily.DHAN_INDIA,
        )


def test_future_requires_underlying_and_expiry() -> None:
    with pytest.raises(ValueError, match="future instrument requires"):
        _instrument(
            instrument_id="bad-future",
            asset_class=AssetClass.FUTURE,
            venue_family=VenueFamily.DHAN_INDIA,
        )
