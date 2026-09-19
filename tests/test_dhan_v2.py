import struct
from datetime import UTC, datetime, timedelta

import pytest

from aura.data.dhan_v2 import (
    DhanFeedDecodeError,
    DhanFullPacket,
    DhanOpenInterestPacket,
    DhanQuotePacket,
    DhanTickerPacket,
    UnsupportedDhanFeedPacket,
    decode_dhan_v2_packet,
    dhan_packet_to_live_events,
)
from aura.data.live_plane import DataDomain

HEADER = struct.Struct("<BHBI")


def _header(code: int, length: int, segment: int = 2, security_id: int = 1333) -> bytes:
    return HEADER.pack(code, length, segment, security_id)


def test_ticker_packet_decodes_little_endian_header_and_epoch() -> None:
    epoch = 1_767_225_600
    raw = _header(2, 16) + struct.pack("<fi", 123.5, epoch)
    packet = decode_dhan_v2_packet(raw)

    assert isinstance(packet, DhanTickerPacket)
    assert packet.header.response_code == 2
    assert packet.header.message_length == 16
    assert packet.header.exchange_segment == 2
    assert packet.header.security_id == 1333
    assert packet.last_price == pytest.approx(123.5)
    assert packet.last_trade_time == datetime.fromtimestamp(epoch, tz=UTC)


def test_quote_packet_decodes_documented_50_byte_layout() -> None:
    epoch = 1_767_225_600
    payload = struct.pack(
        "<fhifiiiffff",
        250.25,
        12,
        epoch,
        248.5,
        100_000,
        4_500,
        5_500,
        245.0,
        240.0,
        252.0,
        243.0,
    )
    packet = decode_dhan_v2_packet(_header(4, 50) + payload)

    assert isinstance(packet, DhanQuotePacket)
    assert packet.last_quantity == 12
    assert packet.volume == 100_000
    assert packet.total_sell_quantity == 4_500
    assert packet.total_buy_quantity == 5_500
    assert packet.day_high == pytest.approx(252.0)
    assert packet.day_low == pytest.approx(243.0)


def test_oi_packet_maps_to_open_interest_live_domain() -> None:
    raw = _header(5, 12) + struct.pack("<i", 123_456)
    packet = decode_dhan_v2_packet(raw)
    assert isinstance(packet, DhanOpenInterestPacket)

    received = datetime(2026, 1, 1, tzinfo=UTC)
    events = dhan_packet_to_live_events(
        packet,
        received_at=received,
        subject_resolver=lambda segment, security: f"NSE_FNO:{security}",
    )
    assert len(events) == 1
    assert events[0].domain == DataDomain.OPEN_INTEREST
    assert events[0].subject == "NSE_FNO:1333"
    assert events[0].payload["open_interest"] == 123_456


def test_full_packet_decodes_trade_oi_and_five_depth_levels() -> None:
    epoch = 1_767_225_600
    base = struct.pack(
        "<fhifiiiiiiffff",
        100.5,
        7,
        epoch,
        99.5,
        10_000,
        1_500,
        1_750,
        20_000,
        24_000,
        18_000,
        98.0,
        97.0,
        102.0,
        96.0,
    )
    depth = b"".join(
        struct.pack(
            "<iihhff",
            1000 + level,
            900 + level,
            10 + level,
            11 + level,
            100.0 - level * 0.05,
            100.1 + level * 0.05,
        )
        for level in range(5)
    )
    raw = _header(8, 162) + base + depth
    assert len(raw) == 162

    packet = decode_dhan_v2_packet(raw)
    assert isinstance(packet, DhanFullPacket)
    assert packet.open_interest == 20_000
    assert len(packet.depth) == 5
    assert packet.depth[0].bid_quantity == 1000
    assert packet.depth[4].ask_orders == 15
    assert packet.depth[0].bid_price == pytest.approx(100.0)

    received = datetime.fromtimestamp(epoch, tz=UTC) + timedelta(milliseconds=20)
    events = dhan_packet_to_live_events(packet, received_at=received)
    assert {event.domain for event in events} == {
        DataDomain.MARKET_TICK,
        DataDomain.OPEN_INTEREST,
        DataDomain.ORDER_BOOK,
    }
    book = next(event for event in events if event.domain == DataDomain.ORDER_BOOK)
    assert len(book.payload["levels"]) == 5


def test_header_message_length_mismatch_is_rejected() -> None:
    raw = _header(2, 99) + struct.pack("<fi", 100.0, 1_767_225_600)
    with pytest.raises(DhanFeedDecodeError, match="length mismatch"):
        decode_dhan_v2_packet(raw)


def test_unknown_response_code_fails_closed() -> None:
    raw = _header(99, 8)
    with pytest.raises(UnsupportedDhanFeedPacket, match="unsupported"):
        decode_dhan_v2_packet(raw)
