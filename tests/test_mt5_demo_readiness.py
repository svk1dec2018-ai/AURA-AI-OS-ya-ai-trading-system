from __future__ import annotations

from decimal import Decimal

from aura.data.mt5_demo import MT5DemoCredentials, OfficialMT5Gateway
from aura.ops.mt5_demo_readiness import inspect_mt5_demo_readiness, resolve_xauusd_symbol


class FakeMT5Readiness:
    TIMEFRAME_M1 = 1

    def __init__(self, *, connected: bool = True, live_account: bool = False) -> None:
        self.connected = connected
        self.live_account = live_account
        self.order_send_called = False
        self.selected: list[tuple[str, bool]] = []

    def initialize(self, *args, **kwargs):
        return True

    def shutdown(self):
        return None

    def account_info(self):
        return {
            "login": 123456,
            "trade_mode": 2 if self.live_account else 0,
            "trade_allowed": True,
            "trade_expert": True,
            "server": "Broker-Demo",
            "currency": "USD",
            "balance": 10000,
            "equity": 10000,
            "margin": 0,
            "margin_free": 10000,
            "margin_level": 0,
        }

    def terminal_info(self):
        return {"connected": self.connected}

    def symbols_get(self):
        return (
            {
                "name": "XAUUSD",
                "description": "Gold vs US Dollar",
                "path": "Metals",
                "trade_mode": 0,
            },
            {
                "name": "XAUUSDm",
                "description": "Gold vs US Dollar",
                "path": "Metals\\Standard",
                "trade_mode": 4,
            },
            {
                "name": "EURUSD",
                "description": "Euro vs US Dollar",
                "path": "Forex",
                "trade_mode": 4,
            },
        )

    def symbol_info(self, symbol):
        if symbol != "XAUUSDm":
            return None
        return {
            "name": symbol,
            "visible": False,
            "trade_mode": 4,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
        }

    def symbol_select(self, symbol, enable):
        self.selected.append((symbol, enable))
        return True

    def symbol_info_tick(self, symbol):
        return {"bid": 2399.8, "ask": 2400.1}

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        assert symbol == "XAUUSDm"
        assert timeframe == self.TIMEFRAME_M1
        assert start_pos == 1
        return (
            {
                "time": 1_700_000_000,
                "open": 2398.0,
                "high": 2401.0,
                "low": 2397.5,
                "close": 2400.0,
                "tick_volume": 100,
                "real_volume": 0,
            },
            {
                "time": 1_700_000_060,
                "open": 2400.0,
                "high": 2402.0,
                "low": 2399.0,
                "close": 2401.0,
                "tick_volume": 120,
                "real_volume": 0,
            },
        )[-count:]

    def order_send(self, request):
        self.order_send_called = True
        raise AssertionError("readiness checker must never submit an order")

    def last_error(self):
        return (0, "ok")


def _gateway(module: FakeMT5Readiness) -> OfficialMT5Gateway:
    gateway = OfficialMT5Gateway(module)
    gateway.connect_demo(MT5DemoCredentials(123456, "secret", "Broker-Demo"))
    return gateway


def test_resolve_xauusd_prefers_tradable_broker_suffix() -> None:
    gateway = _gateway(FakeMT5Readiness())
    assert resolve_xauusd_symbol(gateway) == "XAUUSDm"


def test_mt5_demo_readiness_is_no_order_and_checks_closed_candles() -> None:
    module = FakeMT5Readiness()
    gateway = _gateway(module)

    report = inspect_mt5_demo_readiness(gateway)

    assert report.ready
    assert report.resolved_symbol == "XAUUSDm"
    assert report.server == "Broker-Demo"
    assert report.order_submission_attempted is False
    assert module.order_send_called is False
    assert module.selected == [("XAUUSDm", True)]
    assert [check.name for check in report.checks] == [
        "demo-account",
        "terminal-connected",
        "xauusd-symbol",
        "symbol-metadata",
        "live-tick",
        "closed-candle",
    ]
    assert Decimal(report.checks[4].detail.split("bid=")[1].split()[0]) > 0


def test_mt5_demo_readiness_fails_closed_when_terminal_disconnected() -> None:
    module = FakeMT5Readiness(connected=False)
    gateway = _gateway(module)

    report = inspect_mt5_demo_readiness(gateway)

    assert not report.ready
    assert report.checks[-1].name == "terminal-connected"
    assert report.checks[-1].passed is False
    assert report.order_submission_attempted is False
    assert module.order_send_called is False


def test_mt5_live_account_is_rejected_before_readiness_inspection() -> None:
    module = FakeMT5Readiness(live_account=True)
    gateway = OfficialMT5Gateway(module)

    try:
        gateway.connect_demo(MT5DemoCredentials(123456, "secret", "Broker-Demo"))
    except Exception as exc:
        assert "not DEMO" in str(exc)
    else:
        raise AssertionError("live account must never pass DEMO verification")
    assert module.order_send_called is False
