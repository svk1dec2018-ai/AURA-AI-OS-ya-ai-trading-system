from __future__ import annotations

import hashlib
import json
import struct
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from aura.data.live_plane import DataDomain, LiveDataEvent


class DhanFeedDecodeError(ValueError):
    pass


class UnsupportedDhanFeedPacket(DhanFeedDecodeError):
    pass


class DhanFeedHeader(BaseModel):
    model_config = ConfigDict(frozen=True)

    response_code: int = Field(ge=0, le=255)
    message_length: int = Field(gt=0)
    exchange_segment: int = Field(ge=0, le=255)
    security_id: int = Field(ge=0)


class DhanDepthLevel(BaseModel):
    model_config = ConfigDict(frozen=True)

    bid_quantity: int = Field(ge=0)
    ask_quantity: int = Field(ge=0)
    bid_orders: int = Field(ge=0)
    ask_orders: int = Field(ge=0)
    bid_price: float = Field(ge=0)
    ask_price: float = Field(ge=0)


class DhanTickerPacket(BaseModel):
    model_config = ConfigDict(frozen=True)

    header: DhanFeedHeader
    last_price: float = Field(ge=0)
    last_trade_time: datetime


class DhanQuotePacket(BaseModel):
    model_config = ConfigDict(frozen=True)

    header: DhanFeedHeader
    last_price: float = Field(ge=0)
    last_quantity: int = Field(ge=0)
    last_trade_time: datetime
    average_price: float = Field(ge=0)
    volume: int = Field(ge=0)
    total_sell_quantity: int = Field(ge=0)
    total_buy_quantity: int = Field(ge=0)
    day_open: float = Field(ge=0)
    day_close: float = Field(ge=0)
    day_high: float = Field(ge=0)
    day_low: float = Field(ge=0)


class DhanOpenInterestPacket(BaseModel):
    model_config = ConfigDict(frozen=True)

    header: DhanFeedHeader
    open_interest: int = Field(ge=0)


class DhanPrevClosePacket(BaseModel):
    model_config = ConfigDict(frozen=True)

    header: DhanFeedHeader
    previous_close: float = Field(ge=0)
    previous_open_interest: int = Field(ge=0)


class DhanFullPacket(BaseModel):
    model_config = ConfigDict(frozen=True)

    header: DhanFeedHeader
    last_price: float = Field(ge=0)
    last_quantity: int = Field(ge=0)
    last_trade_time: datetime
    average_price: float = Field(ge=0)
    volume: int = Field(ge=0)
    total_sell_quantity: int = Field(ge=0)
    total_buy_quantity: int = Field(ge=0)
    open_interest: int = Field(ge=0)
    high_open_interest: int = Field(ge=0)
    low_open_interest: int = Field(ge=0)
    day_open: float = Field(ge=0)
    day_close: float = Field(ge=0)
    day_high: float = Field(ge=0)
    day_low: float = Field(ge=0)
    depth: tuple[DhanDepthLevel, ...]


class DhanDisconnectPacket(BaseModel):
    model_config = ConfigDict(frozen=True)

    header: DhanFeedHeader
    reason_code: int


DhanDecodedPacket = Annotated[
    DhanTickerPacket
    | DhanQuotePacket
    | DhanOpenInterestPacket
    | DhanPrevClosePacket
    | DhanFullPacket
    | DhanDisconnectPacket,
    Field(discriminator=None),
]


_HEADER = struct.Struct("<BHBI")
_TICKER = struct.Struct("<fi")
_QUOTE = struct.Struct("<fhifiiiffff")
_OI = struct.Struct("<i")
_PREV_CLOSE = struct.Struct("<fi")
_FULL_BASE = struct.Struct("<fhifiiiiiiffff")
_DEPTH = struct.Struct("<iihhff")
_DISCONNECT = struct.Struct("<h")

_EXPECTED_LENGTHS = {
    2: 16,
    4: 50,
    5: 12,
    6: 16,
    8: 162,
    50: 10,
}


def decode_dhan_v2_packet(data: bytes) -> DhanDecodedPacket:
    """Decode one DhanHQ v2 8-byte-header market-feed packet.

    Dhan's v2 market-feed protocol is little-endian. This decoder intentionally
    supports the packets AURA consumes for trading evidence: ticker, quote, OI,
    previous close, FULL (including five depth levels) and disconnect. Unknown
    response codes fail closed rather than being guessed.
    """

    if len(data) < _HEADER.size:
        raise DhanFeedDecodeError(
            f"Dhan packet truncated: {len(data)} bytes < {_HEADER.size}-byte header"
        )
    response_code, message_length, exchange_segment, security_id = _HEADER.unpack_from(data, 0)
    header = DhanFeedHeader(
        response_code=response_code,
        message_length=message_length,
        exchange_segment=exchange_segment,
        security_id=security_id,
    )
    if message_length != len(data):
        raise DhanFeedDecodeError(
            f"Dhan packet length mismatch: header={message_length}, actual={len(data)}"
        )
    expected = _EXPECTED_LENGTHS.get(response_code)
    if expected is None:
        raise UnsupportedDhanFeedPacket(f"unsupported Dhan feed response code: {response_code}")
    if len(data) != expected:
        raise DhanFeedDecodeError(
            f"invalid Dhan response-code {response_code} length: {len(data)} != {expected}"
        )

    offset = _HEADER.size
    if response_code == 2:
        last_price, epoch = _TICKER.unpack_from(data, offset)
        return DhanTickerPacket(
            header=header,
            last_price=last_price,
            last_trade_time=_epoch(epoch),
        )

    if response_code == 4:
        (
            last_price,
            last_quantity,
            epoch,
            average_price,
            volume,
            total_sell_quantity,
            total_buy_quantity,
            day_open,
            day_close,
            day_high,
            day_low,
        ) = _QUOTE.unpack_from(data, offset)
        return DhanQuotePacket(
            header=header,
            last_price=last_price,
            last_quantity=last_quantity,
            last_trade_time=_epoch(epoch),
            average_price=average_price,
            volume=volume,
            total_sell_quantity=total_sell_quantity,
            total_buy_quantity=total_buy_quantity,
            day_open=day_open,
            day_close=day_close,
            day_high=day_high,
            day_low=day_low,
        )

    if response_code == 5:
        (open_interest,) = _OI.unpack_from(data, offset)
        return DhanOpenInterestPacket(header=header, open_interest=open_interest)

    if response_code == 6:
        previous_close, previous_open_interest = _PREV_CLOSE.unpack_from(data, offset)
        return DhanPrevClosePacket(
            header=header,
            previous_close=previous_close,
            previous_open_interest=previous_open_interest,
        )

    if response_code == 8:
        (
            last_price,
            last_quantity,
            epoch,
            average_price,
            volume,
            total_sell_quantity,
            total_buy_quantity,
            open_interest,
            high_open_interest,
            low_open_interest,
            day_open,
            day_close,
            day_high,
            day_low,
        ) = _FULL_BASE.unpack_from(data, offset)
        depth_offset = _HEADER.size + _FULL_BASE.size
        depth = tuple(
            DhanDepthLevel(
                bid_quantity=bid_quantity,
                ask_quantity=ask_quantity,
                bid_orders=bid_orders,
                ask_orders=ask_orders,
                bid_price=bid_price,
                ask_price=ask_price,
            )
            for bid_quantity, ask_quantity, bid_orders, ask_orders, bid_price, ask_price in (
                _DEPTH.unpack_from(data, depth_offset + level * _DEPTH.size)
                for level in range(5)
            )
        )
        return DhanFullPacket(
            header=header,
            last_price=last_price,
            last_quantity=last_quantity,
            last_trade_time=_epoch(epoch),
            average_price=average_price,
            volume=volume,
            total_sell_quantity=total_sell_quantity,
            total_buy_quantity=total_buy_quantity,
            open_interest=open_interest,
            high_open_interest=high_open_interest,
            low_open_interest=low_open_interest,
            day_open=day_open,
            day_close=day_close,
            day_high=day_high,
            day_low=day_low,
            depth=depth,
        )

    (reason_code,) = _DISCONNECT.unpack_from(data, offset)
    return DhanDisconnectPacket(header=header, reason_code=reason_code)


def dhan_packet_to_live_events(
    packet: DhanDecodedPacket,
    *,
    received_at: datetime,
    subject_resolver: Callable[[int, int], str] | None = None,
    source_id: str = "dhan-v2",
) -> tuple[LiveDataEvent, ...]:
    """Convert a decoded Dhan packet into canonical AURA point-in-time events."""

    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    header = packet.header
    resolver = subject_resolver or (
        lambda exchange_segment, security_id: f"DHAN:{exchange_segment}:{security_id}"
    )
    subject = resolver(header.exchange_segment, header.security_id)
    fingerprint = _packet_fingerprint(packet)

    if isinstance(packet, DhanDisconnectPacket):
        return (
            _event(
                packet=packet,
                domain=DataDomain.EXECUTION,
                subject=subject,
                observed_at=received_at,
                received_at=received_at,
                payload={"event": "feed_disconnect", "reason_code": packet.reason_code},
                source_id=source_id,
                fingerprint=fingerprint,
            ),
        )

    if isinstance(packet, DhanOpenInterestPacket):
        return (
            _event(
                packet=packet,
                domain=DataDomain.OPEN_INTEREST,
                subject=subject,
                observed_at=received_at,
                received_at=received_at,
                payload={"open_interest": packet.open_interest},
                source_id=source_id,
                fingerprint=fingerprint,
            ),
        )

    if isinstance(packet, DhanPrevClosePacket):
        return (
            _event(
                packet=packet,
                domain=DataDomain.MARKET_TICK,
                subject=subject,
                observed_at=received_at,
                received_at=received_at,
                payload={
                    "event": "previous_close",
                    "previous_close": packet.previous_close,
                    "previous_open_interest": packet.previous_open_interest,
                },
                source_id=source_id,
                fingerprint=fingerprint,
            ),
        )

    if isinstance(packet, DhanTickerPacket):
        return (
            _event(
                packet=packet,
                domain=DataDomain.MARKET_TICK,
                subject=subject,
                observed_at=packet.last_trade_time,
                received_at=received_at,
                payload={"last_price": packet.last_price},
                source_id=source_id,
                fingerprint=fingerprint,
            ),
        )

    trade_payload = {
        "last_price": packet.last_price,
        "last_quantity": packet.last_quantity,
        "average_price": packet.average_price,
        "volume": packet.volume,
        "total_sell_quantity": packet.total_sell_quantity,
        "total_buy_quantity": packet.total_buy_quantity,
        "day_open": packet.day_open,
        "day_close": packet.day_close,
        "day_high": packet.day_high,
        "day_low": packet.day_low,
    }
    events = [
        _event(
            packet=packet,
            domain=DataDomain.MARKET_TICK,
            subject=subject,
            observed_at=packet.last_trade_time,
            received_at=received_at,
            payload=trade_payload,
            source_id=source_id,
            fingerprint=fingerprint,
        )
    ]
    if isinstance(packet, DhanFullPacket):
        events.extend(
            (
                _event(
                    packet=packet,
                    domain=DataDomain.OPEN_INTEREST,
                    subject=subject,
                    observed_at=packet.last_trade_time,
                    received_at=received_at,
                    payload={
                        "open_interest": packet.open_interest,
                        "high_open_interest": packet.high_open_interest,
                        "low_open_interest": packet.low_open_interest,
                    },
                    source_id=source_id,
                    fingerprint=fingerprint,
                ),
                _event(
                    packet=packet,
                    domain=DataDomain.ORDER_BOOK,
                    subject=subject,
                    observed_at=packet.last_trade_time,
                    received_at=received_at,
                    payload={"levels": [level.model_dump(mode="python") for level in packet.depth]},
                    source_id=source_id,
                    fingerprint=fingerprint,
                ),
            )
        )
    return tuple(events)


def _event(
    *,
    packet: DhanDecodedPacket,
    domain: DataDomain,
    subject: str,
    observed_at: datetime,
    received_at: datetime,
    payload: dict,
    source_id: str,
    fingerprint: str,
) -> LiveDataEvent:
    return LiveDataEvent(
        event_id=(
            f"{source_id}:{packet.header.response_code}:{packet.header.exchange_segment}:"
            f"{packet.header.security_id}:{domain.value}:{fingerprint}"
        ),
        source_id=source_id,
        domain=domain,
        subject=subject,
        observed_at=observed_at,
        received_at=received_at,
        payload=payload,
        trust_score=1.0,
    )


def _epoch(value: int) -> datetime:
    if value < 0:
        raise DhanFeedDecodeError(f"negative Dhan epoch timestamp: {value}")
    return datetime.fromtimestamp(value, tz=UTC)


def _packet_fingerprint(packet: DhanDecodedPacket) -> str:
    canonical = json.dumps(
        packet.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:24]
