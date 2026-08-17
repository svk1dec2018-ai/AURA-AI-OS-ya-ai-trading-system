from __future__ import annotations

import asyncio
import json
import os
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import websockets

from aura.data.candle_aggregation import (
    CandleSession,
    CanonicalTradeTick,
    SessionCandleAggregator,
)
from aura.domain.models import NormalizedCandle
from aura.markets.universe import CanonicalInstrument

DHAN_FEED_URL = "wss://api-feed.dhan.co"
DHAN_TICKER_SUBSCRIBE_CODE = 15
DHAN_DISCONNECT_CODE = 12
DHAN_MAX_INSTRUMENTS_PER_MESSAGE = 100
DHAN_MAX_INSTRUMENTS_PER_CONNECTION = 5000

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
class DhanLiveCredentials:
    client_id: str
    access_token: str

    def __post_init__(self) -> None:
        if not self.client_id or not self.access_token:
            raise ValueError("Dhan client_id/access_token are required")


def load_dhan_live_credentials_from_env() -> DhanLiveCredentials:
    client_id = os.environ.get("AURA_DHAN_CLIENT_ID", "").strip()
    access_token = os.environ.get("AURA_DHAN_ACCESS_TOKEN", "").strip()
    if not client_id or not access_token:
        raise RuntimeError("set AURA_DHAN_CLIENT_ID and AURA_DHAN_ACCESS_TOKEN")
    return DhanLiveCredentials(client_id=client_id, access_token=access_token)


@dataclass(slots=True, frozen=True)
class DhanTickerSubscription:
    exchange_segment: str
    security_id: str
    symbol: str


@dataclass(slots=True, frozen=True)
class DhanTickerPacket:
    exchange_segment: str
    security_id: str
    last_price: Decimal
    last_trade_time: datetime


def build_ticker_subscriptions(
    instruments: tuple[CanonicalInstrument, ...] | list[CanonicalInstrument],
) -> tuple[DhanTickerSubscription, ...]:
    subscriptions: list[DhanTickerSubscription] = []
    seen: set[tuple[str, str]] = set()
    for instrument in instruments:
        if not instrument.segment:
            continue
        key = (instrument.segment, instrument.venue_symbol)
        if key in seen:
            continue
        seen.add(key)
        subscriptions.append(
            DhanTickerSubscription(
                exchange_segment=instrument.segment,
                security_id=instrument.venue_symbol,
                symbol=instrument.canonical_symbol,
            )
        )
    if len(subscriptions) > DHAN_MAX_INSTRUMENTS_PER_CONNECTION:
        raise ValueError(
            f"Dhan connection plan has {len(subscriptions)} instruments; "
            f"maximum is {DHAN_MAX_INSTRUMENTS_PER_CONNECTION}"
        )
    return tuple(subscriptions)


def decode_dhan_ticker_packet(packet: bytes) -> DhanTickerPacket | None:
    """Decode Dhan v2 response-code 2 ticker packet (little-endian)."""
    if len(packet) < 8:
        raise ValueError("Dhan packet shorter than 8-byte header")
    response_code, message_length, exchange_code, security_id = struct.unpack_from(
        "<BHBI", packet, 0
    )
    if message_length != len(packet):
        raise ValueError(
            f"Dhan packet length mismatch: header={message_length} actual={len(packet)}"
        )
    if response_code != 2:
        return None
    if len(packet) != 16:
        raise ValueError(f"unexpected Dhan ticker packet length: {len(packet)}")
    exchange_segment = _SEGMENT_CODE_TO_NAME.get(exchange_code)
    if exchange_segment is None:
        raise ValueError(f"unknown Dhan exchange segment code: {exchange_code}")
    last_price = Decimal(str(struct.unpack_from("<f", packet, 8)[0]))
    epoch_seconds = struct.unpack_from("<I", packet, 12)[0]
    if last_price <= 0 or epoch_seconds <= 0:
        raise ValueError("invalid Dhan ticker price/time")
    return DhanTickerPacket(
        exchange_segment=exchange_segment,
        security_id=str(security_id),
        last_price=last_price,
        last_trade_time=datetime.fromtimestamp(epoch_seconds, tz=UTC),
    )


class DhanLiveTickerSource:
    """Resilient Dhan v2 Ticker-mode stream for the planned broad universe."""

    def __init__(
        self,
        credentials: DhanLiveCredentials,
        subscriptions: tuple[DhanTickerSubscription, ...],
        *,
        reconnect_min_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
    ) -> None:
        if not subscriptions:
            raise ValueError("Dhan ticker source requires subscriptions")
        if len(subscriptions) > DHAN_MAX_INSTRUMENTS_PER_CONNECTION:
            raise ValueError("Dhan subscription count exceeds one-connection cap")
        if reconnect_min_seconds <= 0 or reconnect_max_seconds < reconnect_min_seconds:
            raise ValueError("invalid Dhan reconnect policy")
        self.credentials = credentials
        self.subscriptions = subscriptions
        self.reconnect_min_seconds = reconnect_min_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self._symbol_by_key = {
            (item.exchange_segment, item.security_id): item.symbol
            for item in subscriptions
        }
        self._stopped = False

    @property
    def url(self) -> str:
        query = urlencode(
            {
                "version": "2",
                "token": self.credentials.access_token,
                "clientId": self.credentials.client_id,
                "authType": "2",
            }
        )
        return f"{DHAN_FEED_URL}?{query}"

    def stop(self) -> None:
        self._stopped = True

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
                            self._validate_text_message(message)
                            continue
                        packet = decode_dhan_ticker_packet(bytes(message))
                        if packet is None:
                            continue
                        symbol = self._symbol_by_key.get(
                            (packet.exchange_segment, packet.security_id)
                        )
                        if symbol is None:
                            continue
                        yield CanonicalTradeTick(
                            symbol=symbol,
                            venue="DHAN_LIVE",
                            price=packet.last_price,
                            quantity=Decimal(0),
                            timestamp=packet.last_trade_time,
                        )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - reconnect loop isolates transport failures
                if self._stopped:
                    break
                await asyncio.sleep(backoff)
                backoff = min(self.reconnect_max_seconds, backoff * 2)

    async def _subscribe(self, socket) -> None:
        for start in range(0, len(self.subscriptions), DHAN_MAX_INSTRUMENTS_PER_MESSAGE):
            chunk = self.subscriptions[
                start : start + DHAN_MAX_INSTRUMENTS_PER_MESSAGE
            ]
            message = {
                "RequestCode": DHAN_TICKER_SUBSCRIBE_CODE,
                "InstrumentCount": len(chunk),
                "InstrumentList": [
                    {
                        "ExchangeSegment": item.exchange_segment,
                        "SecurityId": item.security_id,
                    }
                    for item in chunk
                ],
            }
            await socket.send(json.dumps(message, separators=(",", ":")))

    @staticmethod
    def _validate_text_message(message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        response_code = payload.get("ResponseCode") or payload.get("responseCode")
        if response_code in {50, "50"}:
            raise RuntimeError(f"Dhan feed disconnected: {payload}")


class DhanLiveCandleSource:
    """Turn Dhan ticker stream into grouped, session-anchored closed candles."""

    def __init__(
        self,
        ticker_source: DhanLiveTickerSource,
        *,
        timeframes: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "4h"),
        flush_interval_seconds: float = 1.0,
        batch_lag_seconds: float = 2.0,
    ) -> None:
        if flush_interval_seconds <= 0 or batch_lag_seconds < 0:
            raise ValueError("invalid Dhan candle flush policy")
        self.ticker_source = ticker_source
        self.aggregator = SessionCandleAggregator(
            timeframes=timeframes,
            session=CandleSession(
                timezone="Asia/Kolkata",
                session_start=time(9, 15),
            ),
        )
        self.flush_interval_seconds = flush_interval_seconds
        self.batch_lag_seconds = batch_lag_seconds
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True
        self.ticker_source.stop()

    async def batches(self) -> AsyncIterator[tuple[NormalizedCandle, ...]]:
        queue: asyncio.Queue[CanonicalTradeTick | None] = asyncio.Queue(maxsize=10000)

        async def reader() -> None:
            try:
                async for tick in self.ticker_source.ticks():
                    await queue.put(tick)
                    if self._stopped:
                        break
            finally:
                await queue.put(None)

        reader_task = asyncio.create_task(reader())
        pending: dict[datetime, dict[tuple[str, str], NormalizedCandle]] = {}
        try:
            while not self._stopped:
                try:
                    tick = await asyncio.wait_for(
                        queue.get(), timeout=self.flush_interval_seconds
                    )
                except TimeoutError:
                    tick = None
                if tick is not None:
                    for candle in self.aggregator.on_tick(tick):
                        pending.setdefault(candle.close_time, {})[
                            (candle.symbol, candle.timeframe)
                        ] = candle
                now = datetime.now(UTC)
                for candle in self.aggregator.flush_until(now):
                    pending.setdefault(candle.close_time, {})[
                        (candle.symbol, candle.timeframe)
                    ] = candle
                cutoff = now - timedelta(seconds=self.batch_lag_seconds)
                ready = [close_time for close_time in pending if close_time <= cutoff]
                for close_time in sorted(ready):
                    batch = tuple(
                        sorted(
                            pending.pop(close_time).values(),
                            key=lambda item: (item.symbol, item.timeframe),
                        )
                    )
                    if batch:
                        yield batch
                if tick is None and reader_task.done() and queue.empty():
                    break
        finally:
            self.stop()
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)
