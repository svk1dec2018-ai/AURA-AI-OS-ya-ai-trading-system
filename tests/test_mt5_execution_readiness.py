from types import SimpleNamespace

from aura.webapp import mt5_preflight


class FakeGateway:
    def __init__(self) -> None:
        self.demo_verified = True
        self.order_check_calls = 0
        self.order_send_calls = 0
        self.shutdown_calls = 0

    def connect_current_demo_session(self):
        return SimpleNamespace(
            login=12345678,
            server="Demo-Server",
            currency="USD",
            balance=10000,
            equity=10000,
            margin=0,
            margin_free=10000,
        )

    def symbol_info(self, symbol):
        return {
            "trade_mode": 1,
            "visible": True,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "point": 0.01,
            "digits": 2,
            "trade_stops_level": 0,
            "trade_exemode": self.constant("SYMBOL_TRADE_EXECUTION_MARKET"),
            "filling_mode": self.constant("SYMBOL_FILLING_IOC"),
        }

    def symbol_select(self, symbol, enable):
        return True

    def symbol_info_tick(self, symbol):
        return {"ask": 2000.0, "bid": 1999.9}

    def order_calc_margin(self, order_type, symbol, volume, price):
        return 20.0

    def order_check(self, request):
        self.order_check_calls += 1
        return {"retcode": 0, "comment": "Done"}

    def order_send(self, request):
        self.order_send_calls += 1
        raise AssertionError("execution readiness must never call order_send")

    def positions_get(self, **kwargs):
        return []

    def last_error(self):
        return (0, "OK")

    def shutdown(self):
        self.shutdown_calls += 1

    def constant(self, name):
        values = {
            "TRADE_ACTION_DEAL": 1,
            "ORDER_TYPE_BUY": 0,
            "ORDER_TYPE_SELL": 1,
            "ORDER_TIME_GTC": 0,
            "SYMBOL_FILLING_IOC": 2,
            "SYMBOL_FILLING_FOK": 1,
            "ORDER_FILLING_IOC": 1,
            "ORDER_FILLING_FOK": 0,
            "SYMBOL_TRADE_EXECUTION_MARKET": 2,
        }
        return values[name]


def test_execution_readiness_order_checks_but_never_sends(monkeypatch) -> None:
    gateway = FakeGateway()
    monkeypatch.setattr(mt5_preflight, "OfficialMT5Gateway", lambda: gateway)

    result = mt5_preflight.mt5_demo_execution_check("XAUUSD")

    assert result["ok"] is True
    assert result["execution_ready"] is True
    assert result["demo_verified"] is True
    assert result["minimum_volume"] == "0.01"
    assert result["margin_required"] == "20.0"
    assert result["order_check_attempted"] is True
    assert result["order_submission_attempted"] is False
    assert result["real_money_enabled"] is False
    assert gateway.order_check_calls == 1
    assert gateway.order_send_calls == 0
    assert gateway.shutdown_calls == 1
