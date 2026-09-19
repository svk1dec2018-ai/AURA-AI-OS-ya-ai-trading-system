from datetime import UTC, datetime
from decimal import Decimal

from aura.data.dhan_option_context import (
    DhanOptionTarget,
    DhanOptionTargetResolver,
    build_dhan_option_context_snapshot,
)
from aura.markets.universe import AssetClass, CanonicalInstrument, OptionType, VenueFamily


def _index() -> CanonicalInstrument:
    return CanonicalInstrument(
        instrument_id="dhan:IDX_I:13",
        canonical_symbol="NIFTY",
        venue_family=VenueFamily.DHAN_INDIA,
        venue_symbol="13",
        asset_class=AssetClass.INDEX,
        exchange="INDEX",
        segment="IDX_I",
        currency="INR",
        tick_size=Decimal("0.05"),
        min_quantity=Decimal(1),
        quantity_step=Decimal(1),
        tradable=False,
    )


def _future() -> CanonicalInstrument:
    return CanonicalInstrument(
        instrument_id="dhan:NSE_FNO:9001",
        canonical_symbol="NIFTY-2026-08-27-FUT",
        venue_family=VenueFamily.DHAN_INDIA,
        venue_symbol="9001",
        asset_class=AssetClass.FUTURE,
        exchange="NSE",
        segment="NSE_FNO",
        currency="INR",
        underlying="NIFTY",
        expiry=datetime(2026, 8, 27, tzinfo=UTC),
        tick_size=Decimal("0.05"),
        min_quantity=Decimal(75),
        quantity_step=Decimal(75),
        lot_size=Decimal(75),
    )


def _option(option_type: OptionType, security_id: str) -> CanonicalInstrument:
    return CanonicalInstrument(
        instrument_id=f"dhan:NSE_FNO:{security_id}",
        canonical_symbol=f"NIFTY-2026-08-27-25650-{option_type.value}",
        venue_family=VenueFamily.DHAN_INDIA,
        venue_symbol=security_id,
        asset_class=AssetClass.OPTION,
        exchange="NSE",
        segment="NSE_FNO",
        currency="INR",
        underlying="NIFTY",
        expiry=datetime(2026, 8, 27, tzinfo=UTC),
        strike=Decimal(25650),
        option_type=option_type,
        tick_size=Decimal("0.05"),
        min_quantity=Decimal(75),
        quantity_step=Decimal(75),
        lot_size=Decimal(75),
    )


def _response() -> dict:
    common = {
        "average_price": 100.0,
        "previous_close_price": 90.0,
        "previous_oi": 100,
        "previous_volume": 100,
        "top_ask_quantity": 500,
        "top_bid_quantity": 500,
    }
    return {
        "status": "success",
        "data": {
            "last_price": 25640.0,
            "oc": {
                "25650.000000": {
                    "ce": {
                        **common,
                        "greeks": {
                            "delta": 0.52,
                            "theta": -10.0,
                            "gamma": 0.001,
                            "vega": 12.0,
                        },
                        "implied_volatility": 10.0,
                        "last_price": 120.0,
                        "oi": 1000,
                        "security_id": 10001,
                        "top_ask_price": 120.2,
                        "top_bid_price": 119.8,
                        "volume": 2000,
                    },
                    "pe": {
                        **common,
                        "greeks": {
                            "delta": -0.48,
                            "theta": -11.0,
                            "gamma": 0.0011,
                            "vega": 11.5,
                        },
                        "implied_volatility": 12.0,
                        "last_price": 125.0,
                        "oi": 2000,
                        "security_id": 10002,
                        "top_ask_price": 125.2,
                        "top_bid_price": 124.8,
                        "volume": 1000,
                    },
                }
            },
        },
    }


def test_option_target_resolver_maps_future_to_exact_index_underlying() -> None:
    resolver = DhanOptionTargetResolver(
        (_index(), _future(), _option(OptionType.CALL, "10001"), _option(OptionType.PUT, "10002"))
    )
    target = resolver.target_for(
        "NIFTY-2026-08-27-FUT",
        as_of=datetime(2026, 8, 18, tzinfo=UTC),
    )
    assert target is not None
    assert target.underlying_symbol == "NIFTY"
    assert target.security_id == "13"
    assert target.segment == "IDX_I"
    assert target.expiry.isoformat() == "2026-08-27"


def test_option_context_snapshot_uses_real_chain_metrics_without_fake_iv_percentile() -> None:
    snapshot = build_dhan_option_context_snapshot(
        _response(),
        target=DhanOptionTarget(
            underlying_symbol="NIFTY",
            security_id="13",
            segment="IDX_I",
            expiry=datetime(2026, 8, 27, tzinfo=UTC).date(),
        ),
        observed_at=datetime(2026, 8, 18, 4, 0, tzinfo=UTC),
    )
    assert snapshot.implied_volatility == 11.0
    assert snapshot.iv_percentile is None
    assert snapshot.put_call_oi_ratio == 2.0
    assert snapshot.put_call_volume_ratio == 0.5
    assert snapshot.contracts == 2
    metadata = snapshot.as_agent_metadata()
    assert metadata["underlying_symbol"] == "NIFTY"
    assert metadata["options_snapshot"]["iv_percentile"] is None
