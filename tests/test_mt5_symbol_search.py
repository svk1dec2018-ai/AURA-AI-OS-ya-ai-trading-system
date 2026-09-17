from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from aura.webapp import mt5_preflight


def test_search_filters_full_universe_before_limit_and_preserves_metadata(monkeypatch):
    instruments = [SimpleNamespace(
        venue_symbol=name, tradable=True, asset_class=SimpleNamespace(value="METAL"),
        currency="USD", tick_size=1, min_quantity=1, quantity_step=1, max_quantity=10,
    ) for name in ("AAA", "BBB", "XAUUSD")]
    gateway = Mock()
    gateway.discover_universe.return_value = instruments
    gateway.symbols_get.return_value = [
        {"name": "AAA", "description": "A", "path": "Stocks", "trade_mode": 4},
        {"name": "BBB", "description": "B", "path": "Stocks", "trade_mode": 4},
        {"name": "XAUUSD", "description": "Gold vs USD", "path": "Metals", "trade_mode": 4},
    ]
    monkeypatch.setattr(mt5_preflight, "OfficialMT5Gateway", lambda: gateway)
    result = mt5_preflight.mt5_demo_preflight(max_symbols=1, query="gold")
    assert result["ok"]
    assert result["tradable_symbol_count"] == 3
    assert result["matched_symbol_count"] == 1
    assert result["symbols"][0]["symbol"] == "XAUUSD"
    assert result["symbols"][0]["description"] == "Gold vs USD"
    assert result["symbols"][0]["trade_mode"] == 4
    assert not result["order_submission_attempted"]
    gateway.order_send.assert_not_called()
    gateway.shutdown.assert_called_once()


def test_symbol_search_rejects_excessive_query():
    with pytest.raises(ValueError, match="120"):
        mt5_preflight.mt5_demo_preflight(query="X" * 121)
