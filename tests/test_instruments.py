from datetime import date
from decimal import Decimal

import pytest

from aura.domain.instruments import (
    AssetClass,
    Instrument,
    OptionRight,
    SymbolMapper,
    SymbolMappingError,
    VenueSymbol,
)


def test_symbol_mapper_is_bidirectional_and_case_normalized() -> None:
    mapper = SymbolMapper()
    mapper.register(VenueSymbol("CRYPTO:BTC-USD", "kraken", "BTC/USD"))
    mapper.register(VenueSymbol("CRYPTO:BTC-USD", "binance", "BTCUSDT"))

    assert mapper.to_venue("crypto:btc-usd", "KRAKEN") == "BTC/USD"
    assert mapper.to_venue("CRYPTO:BTC-USD", "binance") == "BTCUSDT"
    assert mapper.to_canonical("Kraken", "btc/usd") == "CRYPTO:BTC-USD"


def test_symbol_mapper_rejects_collisions() -> None:
    mapper = SymbolMapper()
    mapper.register(VenueSymbol("A", "TEST", "X"))

    with pytest.raises(ValueError, match="collision"):
        mapper.register(VenueSymbol("B", "TEST", "X"))
    with pytest.raises(SymbolMappingError):
        mapper.to_venue("UNKNOWN", "TEST")


def test_option_identity_requires_complete_contract_terms() -> None:
    option = Instrument(
        instrument_id="NSE:NIFTY:2026-08-27:25000:C",
        asset_class=AssetClass.OPTION,
        base="NIFTY",
        quote="INR",
        expiry=date(2026, 8, 27),
        strike=Decimal(25000),
        option_right=OptionRight.CALL,
    )
    assert option.option_right == OptionRight.CALL

    with pytest.raises(ValueError, match="options require"):
        Instrument(
            instrument_id="BAD",
            asset_class=AssetClass.OPTION,
            base="NIFTY",
            quote="INR",
        )
