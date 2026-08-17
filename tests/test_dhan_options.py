from datetime import UTC, datetime
from decimal import Decimal

from aura.data.dhan_options import dhan_option_chain_to_live_events, parse_dhan_option_chain
from aura.data.live_plane import DataDomain


def _response():
    return {
        "data": {
            "last_price": 25642.8,
            "oc": {
                "25650.000000": {
                    "ce": {
                        "average_price": 146.99,
                        "greeks": {
                            "delta": 0.53871,
                            "theta": -15.1539,
                            "gamma": 0.00132,
                            "vega": 12.18593,
                        },
                        "implied_volatility": 9.789,
                        "last_price": 134,
                        "oi": 3_786_445,
                        "previous_close_price": 244.85,
                        "previous_oi": 402_220,
                        "previous_volume": 31_931_705,
                        "security_id": 42528,
                        "top_ask_price": 134,
                        "top_ask_quantity": 1365,
                        "top_bid_price": 133.55,
                        "top_bid_quantity": 1625,
                        "volume": 117_567_970,
                    },
                    "pe": {
                        "average_price": 134.62,
                        "greeks": {
                            "delta": -0.46732,
                            "theta": -10.61131,
                            "gamma": 0.0011,
                            "vega": 11.8,
                        },
                        "implied_volatility": 10.2,
                        "last_price": 128,
                        "oi": 2_000_000,
                        "previous_close_price": 150,
                        "previous_oi": 1_800_000,
                        "previous_volume": 12_000_000,
                        "security_id": 42529,
                        "top_ask_price": 128.1,
                        "top_ask_quantity": 500,
                        "top_bid_price": 127.9,
                        "top_bid_quantity": 650,
                        "volume": 20_000_000,
                    },
                }
            },
        },
        "status": "success",
    }


def test_option_chain_parses_call_put_greeks_and_oi() -> None:
    contracts = parse_dhan_option_chain(
        _response(),
        underlying="NIFTY",
        expiry="2026-08-27",
    )
    assert len(contracts) == 2
    call, put = contracts
    assert call.strike == Decimal("25650.000000")
    assert call.option_type == "CE"
    assert call.greeks.delta == 0.53871
    assert call.open_interest == 3_786_445
    assert put.option_type == "PE"
    assert put.greeks.delta == -0.46732


def test_option_chain_emits_options_greeks_and_oi_events_per_contract() -> None:
    received = datetime(2026, 8, 17, 4, 0, tzinfo=UTC)
    events = dhan_option_chain_to_live_events(
        _response(),
        underlying="NIFTY",
        expiry="2026-08-27",
        received_at=received,
    )
    assert len(events) == 6
    domains = [event.domain for event in events]
    assert domains.count(DataDomain.OPTIONS) == 2
    assert domains.count(DataDomain.GREEKS) == 2
    assert domains.count(DataDomain.OPEN_INTEREST) == 2
    call_greeks = next(
        event
        for event in events
        if event.domain == DataDomain.GREEKS and event.payload["option_type"] == "CE"
    )
    assert call_greeks.payload["delta"] == 0.53871
    assert call_greeks.observed_at == received
