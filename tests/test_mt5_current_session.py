from __future__ import annotations

import pytest

from aura.data.mt5_demo import OfficialMT5Gateway


class FakeCurrentSessionMT5:
    def __init__(self, *, trade_mode: int = 0, connected: bool = True) -> None:
        self.trade_mode = trade_mode
        self.connected = connected
        self.shutdown_called = False
        self.initialize_args = None

    def initialize(self, *args, **kwargs):
        self.initialize_args = (args, kwargs)
        return True

    def shutdown(self):
        self.shutdown_called = True

    def account_info(self):
        return {
            "login": 5056011689,
            "trade_mode": self.trade_mode,
            "trade_allowed": True,
            "trade_expert": True,
            "server": "MetaQuotes-Demo",
            "currency": "USD",
            "balance": 100000,
            "equity": 100000,
            "margin": 0,
            "margin_free": 100000,
            "margin_level": 0,
        }

    def terminal_info(self):
        return {"connected": self.connected}

    def last_error(self):
        return (0, "ok")


def test_current_demo_session_reused_without_credentials() -> None:
    module = FakeCurrentSessionMT5()
    gateway = OfficialMT5Gateway(module)

    account = gateway.connect_current_demo_session()

    assert account.login == 5056011689
    assert account.server == "MetaQuotes-Demo"
    assert gateway.demo_verified
    assert module.initialize_args == ((), {})
    assert not module.shutdown_called


def test_current_session_rejects_disconnected_terminal() -> None:
    module = FakeCurrentSessionMT5(connected=False)
    gateway = OfficialMT5Gateway(module)

    with pytest.raises(RuntimeError, match="not connected"):
        gateway.connect_current_demo_session()

    assert not gateway.demo_verified
    assert module.shutdown_called


def test_current_session_rejects_non_demo_account() -> None:
    module = FakeCurrentSessionMT5(trade_mode=2)
    gateway = OfficialMT5Gateway(module)

    with pytest.raises(RuntimeError):
        gateway.connect_current_demo_session()

    assert not gateway.demo_verified
    assert module.shutdown_called
