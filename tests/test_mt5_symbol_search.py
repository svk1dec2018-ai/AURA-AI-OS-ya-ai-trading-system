from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
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
    gateway.symbol_info_tick.return_value = {
        "time": int(datetime.now(UTC).timestamp()),
    }
    monkeypatch.setattr(mt5_preflight, "OfficialMT5Gateway", lambda: gateway)
    result = mt5_preflight.mt5_demo_preflight(max_symbols=1, query="gold")
    assert result["ok"]
    assert result["tradable_symbol_count"] == 3
    assert result["matched_symbol_count"] == 1
    assert result["symbols"][0]["symbol"] == "XAUUSD"
    assert result["symbols"][0]["description"] == "Gold vs USD"
    assert result["symbols"][0]["trade_mode"] == 4
    assert result["market_clock_ok"] is True
    assert not result["order_submission_attempted"]
    gateway.order_send.assert_not_called()
    gateway.shutdown.assert_called_once()


def test_symbol_search_rejects_excessive_query():
    with pytest.raises(ValueError, match="120"):
        mt5_preflight.mt5_demo_preflight(query="X" * 121)


def test_preflight_surfaces_future_broker_clock_and_never_sends(monkeypatch):
    gateway = Mock()
    instrument = SimpleNamespace(
        venue_symbol="XAUUSD", tradable=True,
        asset_class=SimpleNamespace(value="METAL"), currency="USD", tick_size=1,
        min_quantity=1, quantity_step=1, max_quantity=10,
    )
    gateway.discover_universe.return_value = [instrument]
    gateway.symbols_get.return_value = [
        {"name": "XAUUSD", "description": "Gold", "path": "Metals", "trade_mode": 4}
    ]
    gateway.symbol_info_tick.return_value = {
        "time": int((datetime.now(UTC) + timedelta(hours=3)).timestamp()),
    }
    monkeypatch.setattr(mt5_preflight, "OfficialMT5Gateway", lambda: gateway)
    result = mt5_preflight.mt5_demo_preflight()
    assert result["ok"] is True
    assert result["market_clock_ok"] is False
    assert result["market_clock"]["future_skew_seconds"] > 10_000
    gateway.order_send.assert_not_called()


def test_preflight_uses_active_broker_suffixed_symbol_for_clock(monkeypatch):
    instruments = [SimpleNamespace(
        venue_symbol=name, tradable=True, asset_class=SimpleNamespace(value=asset_class),
        currency="USD", tick_size=1, min_quantity=1, quantity_step=1, max_quantity=10,
    ) for name, asset_class in (("AAPLm", "stock_cfd"), ("XAUUSDm", "metal"))]
    gateway = Mock()
    gateway.discover_universe.return_value = instruments
    gateway.symbols_get.return_value = [
        {"name": "AAPLm", "description": "Apple", "path": "Stocks", "trade_mode": 4},
        {"name": "XAUUSDm", "description": "Gold", "path": "Metals", "trade_mode": 4},
    ]
    now = int(datetime.now(UTC).timestamp())
    gateway.symbol_info_tick.side_effect = lambda symbol: (
        {"time": now} if symbol == "XAUUSDm" else None
    )
    monkeypatch.setattr(mt5_preflight, "OfficialMT5Gateway", lambda: gateway)

    result = mt5_preflight.mt5_demo_preflight()

    assert result["market_clock_ok"] is True
    assert result["market_clock"]["symbol"] == "XAUUSDm"
    gateway.symbol_info_tick.assert_called_once_with("XAUUSDm")


def test_web_preflights_are_serialized(monkeypatch):
    active = 0
    peak = 0

    def fake_unlocked(*, max_symbols=200, query=""):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        import time
        time.sleep(0.01)
        active -= 1
        return {"query": query, "max_symbols": max_symbols}

    monkeypatch.setattr(mt5_preflight, "_mt5_demo_preflight_unlocked", fake_unlocked)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda query: mt5_preflight.mt5_demo_preflight(query=query),
            ("gold", "oil", "btc", "eur"),
        ))
    assert peak == 1
    assert {item["query"] for item in results} == {"gold", "oil", "btc", "eur"}
