import collections
from decimal import Decimal

from aura.data.mt5_contracts import MT5UniverseDiscovery
from aura.markets.universe import AssetClass, VenueFamily

Symbol = collections.namedtuple(
    "Symbol",
    [
        "name",
        "path",
        "currency_base",
        "currency_profit",
        "description",
        "trade_contract_size",
        "point",
        "volume_min",
        "volume_step",
        "volume_max",
        "trade_mode",
        "visible",
    ],
)


class FakeMT5:
    def initialize(self):
        return True

    def shutdown(self):
        return None

    def symbols_get(self):
        return (
            Symbol("EURUSD", "Forex\\Majors", "EUR", "USD", "Euro US Dollar", 100000, 0.00001, 0.01, 0.01, 200, 4, True),
            Symbol("XAUUSD", "Metals", "XAU", "USD", "Gold vs US Dollar", 100, 0.01, 0.01, 0.01, 200, 4, True),
            Symbol("USOIL", "Energies", "", "USD", "Crude Oil", 1000, 0.001, 0.01, 0.01, 200, 4, True),
            Symbol("US30", "Indices", "", "USD", "US Wall Street Index", 1, 0.1, 0.01, 0.01, 100, 4, True),
            Symbol("AAPL", "Stocks\\US", "", "USD", "Apple Inc stock CFD", 1, 0.01, 0.01, 0.01, 100, 4, True),
            Symbol("BTCUSD", "Crypto", "BTC", "USD", "Bitcoin CFD", 1, 0.01, 0.01, 0.01, 20, 4, True),
        )

    def symbol_info(self, symbol):
        raise NotImplementedError

    def symbol_info_tick(self, symbol):
        raise NotImplementedError

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        raise NotImplementedError

    def orders_get(self, **kwargs):
        return ()

    def positions_get(self, **kwargs):
        return ()

    def account_info(self):
        return None

    def order_check(self, request):
        return None

    def order_send(self, request):
        return None

    def last_error(self):
        return (0, "ok")


def test_mt5_discovery_enumerates_full_connected_symbol_set() -> None:
    instruments = MT5UniverseDiscovery(FakeMT5()).discover()
    assert len(instruments) == 6
    assert all(item.venue_family == VenueFamily.EXNESS_MT5 for item in instruments)
    by_symbol = {item.canonical_symbol: item for item in instruments}
    assert by_symbol["EURUSD"].asset_class == AssetClass.FOREX
    assert by_symbol["XAUUSD"].asset_class == AssetClass.METAL
    assert by_symbol["USOIL"].asset_class == AssetClass.ENERGY
    assert by_symbol["US30"].asset_class == AssetClass.INDEX_CFD
    assert by_symbol["AAPL"].asset_class == AssetClass.STOCK_CFD
    assert by_symbol["BTCUSD"].asset_class == AssetClass.CRYPTO_CFD


def test_mt5_contract_metadata_preserves_broker_quantity_rules() -> None:
    xau = next(
        instrument
        for instrument in MT5UniverseDiscovery(FakeMT5()).discover()
        if instrument.canonical_symbol == "XAUUSD"
    )
    assert xau.contract_size == Decimal(100)
    assert xau.tick_size == Decimal("0.01")
    assert xau.min_quantity == Decimal("0.01")
    assert xau.quantity_step == Decimal("0.01")
    assert xau.max_quantity == Decimal(200)
