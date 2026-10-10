from types import SimpleNamespace

import pytest

from aura.data.mt5_contracts import MT5SymbolMetadata, MT5UniverseDiscovery, classify_mt5_asset
from aura.markets.mt5_profile import market_inventory, market_priority
from aura.markets.universe import AssetClass


def instrument(symbol, segment=AssetClass.FOREX, tradable=True):
    return SimpleNamespace(
        venue_symbol=symbol, asset_class=segment, tradable=tradable, market_data_enabled=True
    )


def test_priority_keeps_gold_oil_bitcoin_in_a_small_budget():
    rows = [instrument(s) for s in ("EURUSDm", "AAPL", "WTI.cash", "XAUUSDm", "BTCUSDm", "USDZARm")]
    report = market_inventory(rows, max_symbols=3)
    assert [r["symbol"] for r in report["symbols"] if r["selected"]] == [
        "XAUUSDm",
        "WTI.cash",
        "BTCUSDm",
    ]
    assert report["entry_eligible"] == 6
    assert not report["all_symbols_selected"]
    assert not report["execution_verified"]


def test_all_scope_preserves_exotics_and_all_available_segments():
    rows = [
        instrument("USDZARm"),
        instrument("USOILm", AssetClass.ENERGY),
        instrument("JP225", AssetClass.INDEX_CFD),
        instrument("BTCUSDm", AssetClass.CRYPTO_CFD),
        instrument("XAUUSDm", AssetClass.METAL),
        instrument("CLOSED", tradable=False),
    ]
    report = market_inventory(rows)
    assert report["selected"] == 5
    assert report["all_symbols_selected"]
    assert report["excluded_or_disabled"] == 1
    assert report["segments"]["forex"] == 1
    assert (
        next(m for m in report["priority_markets"] if m["market"] == "ethereum")["state"]
        == "NOT_OFFERED_OR_NOT_ENTRY_ELIGIBLE"
    )
    assert not report["order_submission_attempted"]


@pytest.mark.parametrize("symbol", ["XTIUSDm", "XBRUSD", "XNGUSD", "WTI.cash"])
def test_energy_alias_classification(symbol):
    metadata = MT5SymbolMetadata(name=symbol, point=0.01, volume_min=0.01, volume_step=0.01)
    assert classify_mt5_asset(metadata) == AssetClass.ENERGY


def test_close_only_contract_is_not_entry_eligible():
    raw = SimpleNamespace(
        name="EURUSDm", point=0.00001, volume_min=0.01, volume_step=0.01, trade_mode=3
    )
    gateway = SimpleNamespace(symbols_get=lambda: (raw,))
    assert not MT5UniverseDiscovery(gateway).discover()[0].tradable


@pytest.mark.parametrize("limit", [-1, 1001])
def test_invalid_inventory_budget_fails(limit):
    with pytest.raises(ValueError):
        market_inventory([], max_symbols=limit)


def test_unknown_contract_does_not_become_a_guaranteed_market():
    assert market_priority("USDZARm")[0] > market_priority("BTCUSDm")[0]
