import struct
from datetime import UTC, datetime
from decimal import Decimal

from aura.data.dhan_live_full import decode_dhan_full_packet


def test_decode_dhan_full_packet_with_depth() -> None:
    packet = bytearray(162)
    epoch = int(datetime(2026, 8, 17, 4, 0, tzinfo=UTC).timestamp())
    struct.pack_into("<BHBI", packet, 0, 8, 162, 2, 12345)
    struct.pack_into("<f", packet, 8, 25000.0)
    struct.pack_into("<H", packet, 12, 75)
    struct.pack_into("<I", packet, 14, epoch)
    struct.pack_into("<f", packet, 18, 24990.0)
    struct.pack_into("<I", packet, 22, 100000)
    struct.pack_into("<I", packet, 26, 25000)
    struct.pack_into("<I", packet, 30, 30000)
    struct.pack_into("<I", packet, 34, 500000)
    struct.pack_into("<I", packet, 38, 550000)
    struct.pack_into("<I", packet, 42, 450000)
    struct.pack_into("<f", packet, 46, 24800.0)
    struct.pack_into("<f", packet, 50, 24750.0)
    struct.pack_into("<f", packet, 54, 25100.0)
    struct.pack_into("<f", packet, 58, 24700.0)
    for level in range(5):
        offset = 62 + level * 20
        struct.pack_into("<IIHH", packet, offset, 1000 - level * 10, 900 - level * 10, 4, 5)
        struct.pack_into("<f", packet, offset + 12, 24999.0 - level)
        struct.pack_into("<f", packet, offset + 16, 25001.0 + level)

    snapshot = decode_dhan_full_packet(bytes(packet))
    assert snapshot is not None
    assert snapshot.exchange_segment == "NSE_FNO"
    assert snapshot.security_id == "12345"
    assert snapshot.last_price == Decimal("25000.0")
    assert snapshot.cumulative_volume == 100000
    assert snapshot.open_interest == 500000
    assert len(snapshot.depth) == 5
    assert snapshot.depth[0].bid_price == Decimal("24999.0")
    assert snapshot.depth[0].ask_price == Decimal("25001.0")
    assert snapshot.spread_bps is not None
    assert snapshot.spread_bps < 1.0
    assert snapshot.top_of_book_notional > 0
