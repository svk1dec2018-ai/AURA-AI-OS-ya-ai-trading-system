from __future__ import annotations

from collections import namedtuple
from decimal import Decimal

import pytest

from aura.ops.mt5_demo_trade import (
    _protected_prices,
    _resolve_symbol,
    execute_demo_trade,
)

Symbol = namedtuple(
    "Symbol",
    "name trade_mode point volume_min volume_max volume_step visible filling_mode "
    "trade_exemode trade_stops_level digits",
)
Position = namedtuple("Position", "magic symbol volume type ticket")


class FakeGateway:
    def __init__(self) -> None:
        self.sent = False
        self._symbols = (
            Symbol("XAUUSD", 0, 0.01, 0.01, 100.0, 0.01, True, 2, 2, 10, 2),
            Symbol("XAUUSDm", 4, 0.01, 0.01, 100.0, 0.01, True, 2, 2, 10, 2),
        )
        self.positions: tuple[Position, ...] = ()

    def symbols_get(self):
        return self._symbols

    def symbol_info(self, symbol):
        return next(item for item in self._symbols if item.name == symbol)

    def symbol_select(self, symbol, enable=True):
        return True

    def symbol_info_tick(self, symbol):
        Tick = namedtuple("Tick", "bid ask")
        return Tick(2999.0, 3000.0)

    def positions_get(self, **kwargs):
        return self.positions

    def constant(self, name):
        constants = {
            "SYMBOL_FILLING_IOC": 2,
            "SYMBOL_FILLING_FOK": 1,
            "ORDER_FILLING_IOC": 1,
            "ORDER_FILLING_FOK": 0,
            "ORDER_FILLING_RETURN": 2,
            "SYMBOL_TRADE_EXECUTION_MARKET": 2,
            "ORDER_TYPE_BUY": 0,
            "ORDER_TYPE_SELL": 1,
            "POSITION_TYPE_BUY": 0,
            "POSITION_TYPE_SELL": 1,
            "TRADE_ACTION_DEAL": 1,
            "ORDER_TIME_GTC": 0,
            "TRADE_RETCODE_DONE": 10009,
            "TRADE_RETCODE_DONE_PARTIAL": 10010,
            "TRADE_RETCODE_PLACED": 10008,
        }
        return constants[name]

    def order_calc_margin(self, action, symbol, volume, price):
        return 43.05

    def order_check(self, request):
        Result = namedtuple("Result", "retcode comment")
        return Result(0, "Done")

    def order_send(self, request):
        self.sent = True
        Result = namedtuple("Result", "retcode comment order")
        return Result(10009, "Done", 12345)

    def last_error(self):
        return (0, "ok")


def test_resolver_prefers_tradable_suffix_over_disabled_exact():
    assert _resolve_symbol(FakeGateway(), "XAUUSD") == "XAUUSDm"


def test_protected_prices_are_on_correct_side_of_entry():
    raw = FakeGateway().symbol_info("XAUUSDm")._asdict()
    buy_sl, buy_tp = _protected_prices(
        raw,
        side="BUY",
        entry=Decimal(3000),
        stop_bps=Decimal(50),
        target_bps=Decimal(100),
    )
    sell_sl, sell_tp = _protected_prices(
        raw,
        side="SELL",
        entry=Decimal(3000),
        stop_bps=Decimal(50),
        target_bps=Decimal(100),
    )
    assert buy_sl < Decimal(3000) < buy_tp
    assert sell_tp < Decimal(3000) < sell_sl


def test_existing_aura_position_blocks_duplicate_demo_entry():
    gateway = FakeGateway()
    gateway.positions = (Position(560026, "XAUUSDm", 0.01, 0, 77),)
    with pytest.raises(RuntimeError, match="already has 1 AURA position"):
        execute_demo_trade(
            gateway,
            requested_symbol="XAUUSD",
            side="BUY",
            volume=None,
            stop_bps=Decimal(50),
            target_bps=Decimal(100),
            auto_close_seconds=None,
        )
    assert gateway.sent is False
