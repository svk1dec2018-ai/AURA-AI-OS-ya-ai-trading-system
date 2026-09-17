from pathlib import Path

import pytest

from aura.domain.models import Side
from aura.webapp import server as base
from aura.webapp import server_v3


def test_v3_mt5_preflight_delegates_to_read_only_validator(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        server_v3,
        "mt5_demo_preflight",
        lambda max_symbols: {
            "ok": True,
            "demo_verified": True,
            "connected": True,
            "tradable_symbol_count": max_symbols,
            "account": {"server": "Demo-Server"},
            "symbols": [],
        },
    )
    controller = server_v3.AuraWebControllerV3(state_dir=tmp_path / "state")
    payload = controller.mt5_preflight(max_symbols=25)
    assert payload["ok"] is True
    assert payload["demo_verified"] is True
    assert payload["tradable_symbol_count"] == 25


def test_readiness_does_not_report_stale_learning_as_active(monkeypatch, tmp_path: Path) -> None:
    controller = server_v3.AuraWebControllerV3(state_dir=tmp_path / "state")
    monkeypatch.setattr(controller, "status", lambda: {
        "runtime_running": False,
        "status": {"brain": {"state": "running"}},
        "safety": {"real_money_enabled": False, "fund_transfers_enabled": False,
                   "withdrawals_enabled": False},
    })
    monkeypatch.setattr(controller, "mt5_preflight", lambda max_symbols: {
        "ok": True, "demo_verified": True, "connected": True,
        "tradable_symbol_count": 1,
    })
    assert controller.readiness()["self_learning_runtime_active"] is False


def test_v3_execution_check_delegates_without_granting_submission(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server_v3,
        "mt5_demo_execution_check",
        lambda symbol, side: {
            "ok": True,
            "execution_ready": True,
            "symbol": symbol,
            "side": side.value,
            "order_check_attempted": True,
            "order_submission_attempted": False,
            "real_money_enabled": False,
        },
    )
    controller = server_v3.AuraWebControllerV3(state_dir=tmp_path / "state")
    monkeypatch.setattr(controller, "mt5_preflight", lambda max_symbols, query: {
        "ok": True, "demo_verified": True, "market_clock_ok": True,
    })
    payload = controller.mt5_execution_check(symbol="XAUUSD", side=Side.SELL)
    assert payload["execution_ready"] is True
    assert payload["symbol"] == "XAUUSD"
    assert payload["side"] == "SELL"
    assert payload["order_check_attempted"] is True
    assert payload["order_submission_attempted"] is False
    assert payload["real_money_enabled"] is False


def test_v3_execution_preview_blocks_before_order_check_on_bad_clock(
    tmp_path: Path, monkeypatch
) -> None:
    controller = server_v3.AuraWebControllerV3(state_dir=tmp_path / "state")
    monkeypatch.setattr(controller, "mt5_preflight", lambda max_symbols, query: {
        "ok": True, "demo_verified": True, "market_clock_ok": False,
        "market_clock": {"error": "future timestamp", "future_skew_seconds": 10800},
    })
    called = False

    def should_not_run(symbol, side):
        nonlocal called
        called = True

    monkeypatch.setattr(server_v3, "mt5_demo_execution_check", should_not_run)
    payload = controller.mt5_execution_check(symbol="XAUUSD", side=Side.BUY)
    assert payload["ok"] is False
    assert payload["order_check_attempted"] is False
    assert payload["order_submission_attempted"] is False
    assert payload["market_clock"]["future_skew_seconds"] == 10800
    assert called is False


def test_v3_start_fails_closed_when_mt5_preflight_is_not_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller = server_v3.AuraWebControllerV3(state_dir=tmp_path / "state")
    monkeypatch.setattr(
        controller,
        "mt5_preflight",
        lambda max_symbols: {
            "ok": False,
            "error": "terminal not connected",
            "tradable_symbol_count": 0,
        },
    )
    with pytest.raises(RuntimeError, match="MT5 DEMO preflight failed"):
        controller.start(max_symbols=10, max_batches=100)


def test_v3_start_requires_tradable_symbols(tmp_path: Path, monkeypatch) -> None:
    controller = server_v3.AuraWebControllerV3(state_dir=tmp_path / "state")
    monkeypatch.setattr(
        controller,
        "mt5_preflight",
        lambda max_symbols: {
            "ok": True,
            "demo_verified": True,
            "account": {"server": "Demo-Server"},
            "tradable_symbol_count": 0,
        },
    )
    with pytest.raises(RuntimeError, match="no tradable symbols"):
        controller.start(max_symbols=10, max_batches=100)


def test_v3_start_preserves_base_runtime_and_returns_preflight_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller = server_v3.AuraWebControllerV3(state_dir=tmp_path / "state")
    monkeypatch.setattr(
        controller,
        "mt5_preflight",
        lambda max_symbols: {
            "ok": True,
            "demo_verified": True,
            "account": {"server": "Demo-Server"},
            "tradable_symbol_count": 123,
            "market_clock_ok": True,
        },
    )
    monkeypatch.setattr(
        base.AuraWebController,
        "start",
        lambda self, max_symbols, max_batches: {
            "ok": True,
            "started": True,
            "max_symbols": max_symbols,
            "max_batches": max_batches,
        },
    )
    payload = controller.start(max_symbols=10, max_batches=100)
    assert payload["started"] is True
    assert payload["mt5_preflight"]["demo_verified"] is True
    assert payload["mt5_preflight"]["server"] == "Demo-Server"
    assert payload["mt5_preflight"]["tradable_symbol_count"] == 123


def test_v3_start_blocks_future_broker_clock(tmp_path: Path, monkeypatch) -> None:
    controller = server_v3.AuraWebControllerV3(state_dir=tmp_path / "state")
    monkeypatch.setattr(controller, "mt5_preflight", lambda max_symbols: {
        "ok": True, "demo_verified": True, "account": {"server": "Demo"},
        "tradable_symbol_count": 1, "market_clock_ok": False,
        "market_clock": {"error": "timestamp future", "future_skew_seconds": 10800},
    })
    with pytest.raises(RuntimeError, match="start blocked.*10800"):
        controller.start(max_symbols=1, max_batches=1)


def test_mt5_bridge_surfaces_no_send_execution_check() -> None:
    root = Path(__file__).resolve().parents[1]
    javascript = (root / "aura" / "webapp" / "static" / "mt5-bridge.js").read_text(
        encoding="utf-8"
    )
    assert "Check Execution" in javascript
    assert "/api/mt5/execution-check" in javascript
    assert "order_check" in javascript
    assert "order_send NOT attempted" in javascript


def test_one_click_launcher_uses_fresh_v3_server_after_setup() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "START_AURA_AI_OS.cmd").read_text(encoding="utf-8")
    assert 'pip install --disable-pip-version-check -e ".[mt5]"' in launcher
    assert "MetaTrader5 bridge ready" in launcher
    assert "aura.webapp.server_v3 --port 8766 --open" in launcher
    assert "http://127.0.0.1:8766/api/mt5/preflight" in launcher
    assert 'start "" "http://127.0.0.1:8766' not in launcher


def test_distribution_exposes_owner_and_mt5_demo_entrypoints() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'aura-owner-app = "aura.webapp.server_v3:main"' in text
    assert 'aura-mt5-demo = "aura.ops.mt5_autonomous_demo:main"' in text
