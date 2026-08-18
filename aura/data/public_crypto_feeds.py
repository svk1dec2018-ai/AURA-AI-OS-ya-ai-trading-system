from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import websockets
from websockets.exceptions import WebSocketException

from aura.data.cross_feed import QuoteObservation


class PublicCryptoFeedError(RuntimeError):
    pass


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _positive(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PublicCryptoFeedError(f"invalid {name}: {value!r}") from exc
    if parsed <= 0:
        raise PublicCryptoFeedError(f"{name} must be positive")
    return parsed


def _optional_positive(value: Any, name: str) -> Decimal | None:
    if value in {None, ""}:
        return None
    return _positive(value, name)


def _millis(value: Any) -> datetime:
    try:
        timestamp = int(value)
    except (TypeError, ValueError) as exc:
        raise PublicCryptoFeedError(f"invalid millisecond timestamp: {value!r}") from exc
    if timestamp < 0:
        raise PublicCryptoFeedError("timestamp cannot be negative")
    return datetime.fromtimestamp(timestamp / 1000.0, tz=UTC)


def _iso8601(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise PublicCryptoFeedError("missing ISO-8601 timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PublicCryptoFeedError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PublicCryptoFeedError("provider timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def parse_coinbase_ticker(message: dict[str, Any], *, received_at: datetime) -> tuple[QuoteObservation, ...]:
    """Parse Coinbase Advanced Trade public ticker messages.

    Most Advanced Trade market-data channels are public. AURA accepts only data
    whose provider timestamp is not later than the local receive timestamp.
    """

    _aware(received_at, "received_at")
    if message.get("channel") != "ticker":
        return ()
    observed = _iso8601(message.get("timestamp"))
    if observed > received_at:
        return ()
    quotes: list[QuoteObservation] = []
    for event in message.get("events", []):
        if not isinstance(event, dict):
            continue
        for ticker in event.get("tickers", []):
            if not isinstance(ticker, dict):
                continue
            symbol = str(ticker.get("product_id") or "").strip().upper()
            if not symbol:
                continue
            quotes.append(
                QuoteObservation(
                    provider="COINBASE_PUBLIC",
                    symbol=symbol,
                    last=_positive(ticker.get("price"), "Coinbase price"),
                    bid=_optional_positive(ticker.get("best_bid"), "Coinbase bid"),
                    ask=_optional_positive(ticker.get("best_ask"), "Coinbase ask"),
                    observed_at=observed,
                    received_at=received_at,
                    trust_score=1.0,
                )
            )
    return tuple(quotes)


def parse_bybit_ticker(message: dict[str, Any], *, received_at: datetime) -> tuple[QuoteObservation, ...]:
    """Parse Bybit v5 public ticker snapshots/deltas when a last price is present."""

    _aware(received_at, "received_at")
    topic = str(message.get("topic") or "")
    if not topic.startswith("tickers."):
        return ()
    observed = _millis(message.get("ts"))
    if observed > received_at:
        return ()
    raw_data = message.get("data")
    items = raw_data if isinstance(raw_data, list) else [raw_data]
    quotes: list[QuoteObservation] = []
    for item in items:
        if not isinstance(item, dict) or item.get("lastPrice") in {None, ""}:
            continue
        symbol = str(item.get("symbol") or topic.removeprefix("tickers.")).strip().upper()
        if not symbol:
            continue
        quotes.append(
            QuoteObservation(
                provider="BYBIT_PUBLIC",
                symbol=symbol,
                last=_positive(item.get("lastPrice"), "Bybit last price"),
                bid=_optional_positive(item.get("bid1Price"), "Bybit bid"),
                ask=_optional_positive(item.get("ask1Price"), "Bybit ask"),
                observed_at=observed,
                received_at=received_at,
                trust_score=1.0,
            )
        )
    return tuple(quotes)


def parse_okx_ticker(message: dict[str, Any], *, received_at: datetime) -> tuple[QuoteObservation, ...]:
    """Parse OKX v5 public ticker messages."""

    _aware(received_at, "received_at")
    arg = message.get("arg")
    if not isinstance(arg, dict) or arg.get("channel") != "tickers":
        return ()
    quotes: list[QuoteObservation] = []
    for item in message.get("data", []):
        if not isinstance(item, dict):
            continue
        observed = _millis(item.get("ts"))
        if observed > received_at:
            continue
        symbol = str(item.get("instId") or arg.get("instId") or "").strip().upper()
        if not symbol:
            continue
        quotes.append(
            QuoteObservation(
                provider="OKX_PUBLIC",
                symbol=symbol,
                last=_positive(item.get("last"), "OKX last price"),
                bid=_optional_positive(item.get("bidPx"), "OKX bid"),
                ask=_optional_positive(item.get("askPx"), "OKX ask"),
                observed_at=observed,
                received_at=received_at,
                trust_score=1.0,
            )
        )
    return tuple(quotes)


class _ReconnectingPublicTickerFeed:
    endpoint: ClassVar[str]

    def __init__(self, symbols: list[str] | tuple[str, ...]) -> None:
        normalized = tuple(sorted({item.strip().upper() for item in symbols if item.strip()}))
        if not normalized:
            raise ValueError("at least one symbol is required")
        self.symbols = normalized
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def stream(self) -> AsyncIterator[QuoteObservation]:
        backoff = 1.0
        while not self._stopped:
            try:
                async for quote in self._stream_connection():
                    backoff = 1.0
                    yield quote
            except asyncio.CancelledError:
                raise
            except (OSError, TimeoutError, WebSocketException, PublicCryptoFeedError, json.JSONDecodeError):
                if self._stopped:
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _stream_connection(self) -> AsyncIterator[QuoteObservation]:
        raise NotImplementedError


class CoinbasePublicTickerFeed(_ReconnectingPublicTickerFeed):
    endpoint = "wss://advanced-trade-ws.coinbase.com"

    async def _stream_connection(self) -> AsyncIterator[QuoteObservation]:
        async with websockets.connect(self.endpoint, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "subscribe",
                        "product_ids": list(self.symbols),
                        "channel": "ticker",
                    }
                )
            )
            await ws.send(json.dumps({"type": "subscribe", "channel": "heartbeats"}))
            while not self._stopped:
                raw = json.loads(await ws.recv())
                received_at = datetime.now(UTC)
                for quote in parse_coinbase_ticker(raw, received_at=received_at):
                    yield quote


class BybitPublicTickerFeed(_ReconnectingPublicTickerFeed):
    _endpoints: ClassVar[dict[str, str]] = {
        "spot": "wss://stream.bybit.com/v5/public/spot",
        "linear": "wss://stream.bybit.com/v5/public/linear",
        "inverse": "wss://stream.bybit.com/v5/public/inverse",
        "option": "wss://stream.bybit.com/v5/public/option",
    }

    def __init__(self, symbols: list[str] | tuple[str, ...], *, market: str = "spot") -> None:
        super().__init__(symbols)
        market = market.strip().lower()
        if market not in self._endpoints:
            raise ValueError(f"unsupported Bybit public market: {market}")
        self.market = market
        self.endpoint = self._endpoints[market]

    async def _stream_connection(self) -> AsyncIterator[QuoteObservation]:
        async with websockets.connect(self.endpoint, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(
                json.dumps(
                    {
                        "op": "subscribe",
                        "args": [f"tickers.{symbol}" for symbol in self.symbols],
                    }
                )
            )
            while not self._stopped:
                raw = json.loads(await ws.recv())
                received_at = datetime.now(UTC)
                for quote in parse_bybit_ticker(raw, received_at=received_at):
                    yield quote


class OkxPublicTickerFeed(_ReconnectingPublicTickerFeed):
    endpoint = "wss://ws.okx.com:8443/ws/v5/public"

    async def _stream_connection(self) -> AsyncIterator[QuoteObservation]:
        async with websockets.connect(self.endpoint, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(
                json.dumps(
                    {
                        "op": "subscribe",
                        "args": [
                            {"channel": "tickers", "instId": symbol}
                            for symbol in self.symbols
                        ],
                    }
                )
            )
            while not self._stopped:
                raw = json.loads(await ws.recv())
                received_at = datetime.now(UTC)
                for quote in parse_okx_ticker(raw, received_at=received_at):
                    yield quote
