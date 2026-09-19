from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import websockets

from aura.data.candle_aggregation import CanonicalTradeTick
from aura.data.dhan_live_ticker import (
    DHAN_FEED_URL,
    DHAN_MAX_INSTRUMENTS_PER_CONNECTION,
    DHAN_MAX_INSTRUMENTS_PER_MESSAGE,
    DhanLiveCredentials,
    DhanTickerSubscription,
)

DHAN_FULL_SUBSCRIBE_CODE = 21
DHAN_FULL_PACKET_LENGTH = 162

_SEGMENT_CODE_TO_NAME = {
    0: "IDX_I",
    1: "NSE_EQ",
    2: "NSE_FNO",
    3: "NSE_CURRENCY",
    4: "BSE_EQ",
    5: "MCX_COMM",
    7: "BSE_CURRENCY",
    8: "BSE_FNO",
}


@dataclass(slots=True, frozen=True)
class DhanDepthLevel:
    bid_quantity: int
    ask_quantity: int
    bid_orders: int
    ask_orders: int
    bid_price: Decimal
    ask_price: Decimal


@dataclass(slots=True, frozen=True)
class DhanFullSnapshot:
    exchange_segment: str
    security_id: str
    last_price: Decimal
    last_quantity: int
    last_trade_time: datetime
    average_price: Decimal
    cumulative_volume: int
    total_sell_quantity: int
    total_buy_quantity: int
    open_interest: int
    highest_open_interest: int
    lowest_open_interest: int
    open_price: Decimal
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal
    depth: tuple[DhanDepthLevel, ...]

    @property
    def spread_bps(self) -> float | None:
        if not self.depth:
            return None
        best = self.depth[0]
        if best.bid_price <= 0 or best.ask_price <= 0 or best.ask_price < best.bid_price:
            return None
        midpoint = (best.bid_price + best.ask_price) / Decimal(2)
        if midpoint <= 0:
            return None
        return float((best.ask_price - best.bid_price) / midpoint * Decimal(10000))

    @property
    def top_of_book_notional(self) -> Decimal:
        return sum(
            (
                Decimal(level.bid_quantity) * level.bid_price
                + Decimal(level.ask_quantity) * level.ask_price
            )
            for level in self.depth
            if level.bid_price > 0 and level.ask_price > 0
        )


def decode_dhan_full_packet(packet: bytes) -> DhanFullSnapshot | None:
    """Decode Dhan v2 response-code 8 Full packet using documented LE layout."""
    if len(packet) < 8:
        raise ValueError("Dhan packet shorter than header")
    response_code, message_length, exchange_code, security_id = struct.unpack_from(
        "<BHBI", packet, 0
    )
    if message_length != len(packet):
        raise ValueError(
            f"Dhan Full packet length mismatch: header={message_length} actual={len(packet)}"
        )
    if response_code != 8:
        return None
    if len(packet) != DHAN_FULL_PACKET_LENGTH:
        raise ValueError(f"unexpected Dhan Full packet length: {len(packet)}")
    exchange_segment = _SEGMENT_CODE_TO_NAME.get(exchange_code)
    if exchange_segment is None:
        raise ValueError(f"unknown Dhan exchange segment code: {exchange_code}")

    last_price = _f32(packet, 8)
    last_quantity = struct.unpack_from("<H", packet, 12)[0]
    last_trade_epoch = struct.unpack_from("<I", packet, 14)[0]
    average_price = _f32(packet, 18)
    cumulative_volume = struct.unpack_from("<I", packet, 22)[0]
    total_sell_quantity = struct.unpack_from("<I", packet, 26)[0]
    total_buy_quantity = struct.unpack_from("<I", packet, 30)[0]
    open_interest = struct.unpack_from("<I", packet, 34)[0]
    highest_open_interest = struct.unpack_from("<I", packet, 38)[0]
    lowest_open_interest = struct.unpack_from("<I", packet, 42)[0]
    open_price = _f32(packet, 46)
    close_price = _f32(packet, 50)
    high_price = _f32(packet, 54)
    low_price = _f32(packet, 58)
    depth: list[DhanDepthLevel] = []
    offset = 62
    for _ in range(5):
        bid_quantity, ask_quantity, bid_orders, ask_orders = struct.unpack_from(
            "<IIHH", packet, offset
        )
        bid_price = _f32(packet, offset + 12)
        ask_price = _f32(packet, offset + 16)
        depth.append(
            DhanDepthLevel(
                bid_quantity=bid_quantity,
                ask_quantity=ask_quantity,
                bid_orders=bid_orders,
                ask_orders=ask_orders,
                bid_price=bid_price,
                ask_price=ask_price,
            )
        )
        offset += 20
    if last_price <= 0 or last_trade_epoch <= 0:
        raise ValueError("invalid Dhan Full price/time")
    return DhanFullSnapshot(
        exchange_segment=exchange_segment,
        security_id=str(security_id),
        last_price=last_price,
        last_quantity=last_quantity,
        last_trade_time=datetime.fromtimestamp(last_trade_epoch, tz=UTC),
        average_price=average_price,
        cumulative_volume=cumulative_volume,
        total_sell_quantity=total_sell_quantity,
        total_buy_quantity=total_buy_quantity,
        open_interest=open_interest,
        highest_open_interest=highest_open_interest,
        lowest_open_interest=lowest_open_interest,
        open_price=open_price,
        close_price=close_price,
        high_price=high_price,
        low_price=low_price,
        depth=tuple(depth),
    )


class DhanDeepFullSource:
    """Second Dhan connection for expensive Full packets on radar shortlist."""

    def __init__(
        self,
        credentials: DhanLiveCredentials,
        subscriptions: tuple[DhanTickerSubscription, ...],
        *,
        reconnect_min_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
    ) -> None:
        if not subscriptions:
            raise ValueError("Dhan Full source requires subscriptions")
        if len(subscriptions) > DHAN_MAX_INSTRUMENTS_PER_CONNECTION:
            raise ValueError("Dhan Full subscription count exceeds connection cap")
        self.credentials = credentials
        self.subscriptions = subscriptions
        self.reconnect_min_seconds = reconnect_min_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self._symbol_by_key = {
            (item.exchange_segment, item.security_id): item.symbol
            for item in subscriptions
        }
        self._last_volume: dict[str, int] = {}
        self._metadata: dict[str, dict] = {}
        self._stopped = False

    @property
    def url(self) -> str:
        return (
            f"{DHAN_FEED_URL}?version=2&token={self.credentials.access_token}"
            f"&clientId={self.credentials.client_id}&authType=2"
        )

    def stop(self) -> None:
        self._stopped = True

    def metadata_for(self, symbol: str) -> dict:
        snapshot = self._metadata.get(symbol)
        return dict(snapshot) if snapshot is not None else {}

    async def ticks(self) -> AsyncIterator[CanonicalTradeTick]:
        backoff = self.reconnect_min_seconds
        while not self._stopped:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**20,
                ) as socket:
                    await self._subscribe(socket)
                    backoff = self.reconnect_min_seconds
                    async for message in socket:
                        if self._stopped:
                            break
                        if isinstance(message, str):
                            continue
                        snapshot = decode_dhan_full_packet(bytes(message))
                        if snapshot is None:
                            continue
                        symbol = self._symbol_by_key.get(
                            (snapshot.exchange_segment, snapshot.security_id)
                        )
                        if symbol is None:
                            continue
                        previous_volume = self._last_volume.get(symbol)
                        quantity = (
                            max(0, snapshot.cumulative_volume - previous_volume)
                            if previous_volume is not None
                            else 0
                        )
                        self._last_volume[symbol] = snapshot.cumulative_volume
                        self._metadata[symbol] = _metadata(snapshot)
                        yield CanonicalTradeTick(
                            symbol=symbol,
                            venue="DHAN_LIVE_FULL",
                            price=snapshot.last_price,
                            quantity=Decimal(quantity),
                            timestamp=snapshot.last_trade_time,
                        )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - isolate/reconnect feed failures
                if self._stopped:
                    break
                await asyncio.sleep(backoff)
                backoff = min(self.reconnect_max_seconds, backoff * 2)

    async def _subscribe(self, socket) -> None:
        for start in range(0, len(self.subscriptions), DHAN_MAX_INSTRUMENTS_PER_MESSAGE):
            chunk = self.subscriptions[
                start : start + DHAN_MAX_INSTRUMENTS_PER_MESSAGE
            ]
            await socket.send(
                json.dumps(
                    {
                        "RequestCode": DHAN_FULL_SUBSCRIBE_CODE,
                        "InstrumentCount": len(chunk),
                        "InstrumentList": [
                            {
                                "ExchangeSegment": item.exchange_segment,
                                "SecurityId": item.security_id,
                            }
                            for item in chunk
                        ],
                    },
                    separators=(",", ":"),
                )
            )


def _metadata(snapshot: DhanFullSnapshot) -> dict:
    best_bid = snapshot.depth[0].bid_price if snapshot.depth else Decimal(0)
    best_ask = snapshot.depth[0].ask_price if snapshot.depth else Decimal(0)
    spread = snapshot.spread_bps
    return {
        "execution_quality": {
            "source_id": (
                f"dhan:{snapshot.exchange_segment}:{snapshot.security_id}:full"
            ),
            "observed_at": snapshot.last_trade_time.isoformat(),
            "spread_bps": spread if spread is not None else 1_000_000.0,
            "estimated_slippage_bps": (
                spread / 2.0 if spread is not None else 1_000_000.0
            ),
            "top_of_book_notional": float(snapshot.top_of_book_notional),
            "trust_score": 1.0,
            "best_bid": str(best_bid),
            "best_ask": str(best_ask),
        },
        "dhan_derivatives": {
            "open_interest": snapshot.open_interest,
            "highest_open_interest": snapshot.highest_open_interest,
            "lowest_open_interest": snapshot.lowest_open_interest,
            "cumulative_volume": snapshot.cumulative_volume,
            "total_buy_quantity": snapshot.total_buy_quantity,
            "total_sell_quantity": snapshot.total_sell_quantity,
        },
    }


def _f32(packet: bytes, offset: int) -> Decimal:
    return Decimal(str(struct.unpack_from("<f", packet, offset)[0]))
