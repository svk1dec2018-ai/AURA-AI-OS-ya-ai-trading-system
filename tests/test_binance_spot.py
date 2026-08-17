from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.data.binance_spot import (
    BinanceDepthSequenceGuard,
    BinanceStreamError,
    parse_binance_depth_update,
    parse_binance_spot_message,
)
from aura.data.live_plane import DataDomain


def _received(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC) + timedelta(milliseconds=10)


def test_trade_stream_maps_to_market_tick() -> None:
    raw = {
        "e": "trade",
        "E": 1_672_515_782_136,
        "s": "BNBBTC",
        "t": 12345,
        "p": "0.001",
        "q": "100",
        "T": 1_672_515_782_136,
        "m": True,
        "M": True,
    }
    parsed = parse_binance_spot_message(raw, received_at=_received(raw["E"]))
    assert len(parsed.events) == 1
    event = parsed.events[0]
    assert event.domain == DataDomain.MARKET_TICK
    assert event.subject == "BNBBTC"
    assert event.sequence == 12345
    assert event.payload["price"] == "0.001"


def test_combined_stream_closed_kline_emits_normalized_closed_candle() -> None:
    event_ms = 1_672_515_842_000
    message = {
        "stream": "bnbbtc@kline_1m",
        "data": {
            "e": "kline",
            "E": event_ms,
            "s": "BNBBTC",
            "k": {
                "t": 1_672_515_780_000,
                "T": 1_672_515_839_999,
                "s": "BNBBTC",
                "i": "1m",
                "f": 100,
                "L": 200,
                "o": "0.0010",
                "c": "0.0020",
                "h": "0.0025",
                "l": "0.0015",
                "v": "1000",
                "n": 100,
                "x": True,
                "q": "1.0000",
                "V": "500",
                "Q": "0.500",
                "B": "123456",
            },
        },
    }
    parsed = parse_binance_spot_message(message, received_at=_received(event_ms))
    assert parsed.closed_candle is not None
    assert parsed.closed_candle.symbol == "BNBBTC"
    assert parsed.closed_candle.timeframe == "1m"
    assert parsed.closed_candle.close == Decimal("0.0020")
    assert parsed.closed_candle.closed
    assert parsed.events[0].domain == DataDomain.CANDLE


def test_open_kline_is_observable_but_not_decision_candle() -> None:
    event_ms = 1_672_515_782_136
    raw = {
        "e": "kline",
        "E": event_ms,
        "s": "BTCUSDT",
        "k": {
            "t": 1_672_515_780_000,
            "T": 1_672_515_839_999,
            "s": "BTCUSDT",
            "i": "1m",
            "f": 1,
            "L": 2,
            "o": "20000",
            "c": "20001",
            "h": "20002",
            "l": "19999",
            "v": "10",
            "n": 2,
            "x": False,
            "q": "200000",
            "V": "5",
            "Q": "100000",
        },
    }
    parsed = parse_binance_spot_message(raw, received_at=_received(event_ms))
    assert parsed.closed_candle is None
    assert parsed.events[0].payload["closed"] is False


def test_book_ticker_maps_best_bid_ask_with_update_sequence() -> None:
    received = datetime(2026, 1, 1, tzinfo=UTC)
    parsed = parse_binance_spot_message(
        {
            "u": 400900217,
            "s": "BNBUSDT",
            "b": "25.35190000",
            "B": "31.21000000",
            "a": "25.36520000",
            "A": "40.66000000",
        },
        received_at=received,
    )
    event = parsed.events[0]
    assert event.domain == DataDomain.ORDER_BOOK
    assert event.sequence == 400900217
    assert event.payload["best_ask_price"] == "25.36520000"


def test_depth_guard_accepts_bridge_and_detects_gap() -> None:
    guard = BinanceDepthSequenceGuard()
    guard.seed_snapshot(156)
    first = parse_binance_depth_update(
        {
            "e": "depthUpdate",
            "E": 1_672_515_782_136,
            "s": "BNBBTC",
            "U": 157,
            "u": 160,
            "b": [["0.0024", "10"]],
            "a": [["0.0026", "100"]],
        }
    )
    assert guard.apply(first)
    assert guard.last_update_id == 160

    gap = parse_binance_depth_update(
        {
            "e": "depthUpdate",
            "E": 1_672_515_783_136,
            "s": "BNBBTC",
            "U": 170,
            "u": 175,
            "b": [],
            "a": [],
        }
    )
    with pytest.raises(BinanceStreamError, match="gap"):
        guard.apply(gap)
