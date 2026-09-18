from pathlib import Path
from types import SimpleNamespace

from aura.webapp import charting, server_v3


class FakeQuoteGateway:
    def __init__(self) -> None:
        self.shutdown_called = False
        self.selected = None

    def connect_current_demo_session(self):
        return SimpleNamespace(login=12345678, server="Broker-Demo", currency="USD")

    def symbol_info(self, symbol):
        if symbol == "XAUUSD":
            return SimpleNamespace(name="XAUUSD", trade_mode=4, point=0.01, digits=2)
        return None

    def symbols_get(self):
        return (SimpleNamespace(name="XAUUSD", trade_mode=4),)

    def symbol_select(self, symbol, enable=True):
        self.selected = (symbol, enable)
        return True

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(
            time=1760000000,
            time_msc=1760000000123,
            bid=2634.10,
            ask=2634.30,
            last=2634.20,
            volume=12,
            volume_real=12.5,
        )

    def last_error(self):
        return (0, "OK")

    def shutdown(self):
        self.shutdown_called = True


def test_live_quote_is_read_only_and_demo_scoped() -> None:
    gateway = FakeQuoteGateway()
    payload = charting.mt5_live_quote("XAUUSD", gateway=gateway)
    assert payload["ok"] is True
    assert payload["mode"] == "MT5_DEMO_READ_ONLY"
    assert payload["symbol"] == "XAUUSD"
    assert payload["bid"] == 2634.10
    assert payload["ask"] == 2634.30
    assert payload["spread_points"] == 20.0
    assert payload["account"]["login_last4"] == "5678"
    assert payload["execution_authority"] is False
    assert payload["risk_authority"] is False
    assert payload["order_submission_attempted"] is False
    assert gateway.selected == ("XAUUSD", True)
    assert gateway.shutdown_called is False


def test_v3_controller_live_quote_delegates_to_read_only_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        server_v3,
        "mt5_live_quote",
        lambda symbol: {
            "ok": True,
            "symbol": symbol,
            "bid": 1.0,
            "ask": 1.1,
            "execution_authority": False,
        },
    )
    controller = server_v3.AuraWebControllerV3(state_dir=tmp_path / "state")
    payload = controller.live_quote(symbol="EURUSD")
    assert payload["symbol"] == "EURUSD"
    assert payload["execution_authority"] is False


def test_next_dashboard_and_beginner_launchers_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = (
        root / "dashboard" / "package.json",
        root / "dashboard" / "components" / "AuraControlRoom.tsx",
        root / "dashboard" / "components" / "MarketChart.tsx",
        root / "dashboard" / "components" / "AdvancedTools.tsx",
        root / "START_AURA2.cmd",
        root / "STOP_AURA2.cmd",
        root / "scripts" / "start_aura2_dashboard.ps1",
    )
    assert all(path.exists() for path in expected)
    package = (root / "dashboard" / "package.json").read_text(encoding="utf-8")
    chart = (root / "dashboard" / "components" / "MarketChart.tsx").read_text(encoding="utf-8")
    shell = (root / "dashboard" / "components" / "AuraControlRoom.tsx").read_text(encoding="utf-8")
    advanced = (root / "dashboard" / "components" / "AdvancedTools.tsx").read_text(encoding="utf-8")
    launcher = (root / "scripts" / "start_aura2_dashboard.ps1").read_text(encoding="utf-8")
    assert '"next": "16.3.3"' in package
    assert '"lightweight-charts": "5.2.1"' in package
    assert "/api/mt5/quote" in chart
    assert "Bull / Bear / Counterfactual debate" in shell
    assert "Open-source research fusion" in shell
    assert "Trade Journal" in shell
    assert "Strategy Studio" in shell
    assert "All Features" in shell
    assert "/api/journal" in advanced
    assert "/api/backtest/run" in advanced
    assert "/api/mt5/execution-check" in advanced
    assert "AURA_BACKEND_URL=http://127.0.0.1:8766" in launcher
    assert "npm.cmd run build" in launcher
    assert "npm.cmd run start" in launcher
    assert "npm.cmd run dev" not in launcher
    assert "This launcher does not auto-start trading" in launcher
