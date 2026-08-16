from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import websockets

from aura.domain.models import NormalizedCandle


class KrakenFeedError(RuntimeError):
    pass


def _parse_rfc3339(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


class KrakenSpotOhlcFeed:
    """Public Kraken Spot WebSocket v2 OHLC adapter.

    Kraken updates the active OHLC bar on trade events. AURA emits a bar only
    after a later interval is observed, guaranteeing closed-candle semantics.
    """

    endpoint = "wss://ws.kraken.com/v2"
    _allowed_intervals = {1, 5, 15, 30, 60, 240, 1440, 10080, 21600}

    def __init__(self, symbols: list[str], interval_minutes: int = 1) -> None:
        if not symbols:
            raise ValueError("at least one Kraken symbol is required")
        if interval_minutes not in self._allowed_intervals:
            raise ValueError(f"unsupported Kraken OHLC interval: {interval_minutes}")
        self.symbols = symbols
        self.interval_minutes = interval_minutes
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def stream(self) -> AsyncIterator[NormalizedCandle]:
        backoff = 1.0
        while not self._stopped:
            try:
                async for candle in self._stream_connection():
                    backoff = 1.0
                    yield candle
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stopped:
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                last_error = exc
                if backoff >= 30.0 and isinstance(last_error, KrakenFeedError):
                    # Continue retrying, but preserve a bounded reconnect rate.
                    pass

    async def _stream_connection(self) -> AsyncIterator[NormalizedCandle]:
        latest: dict[str, NormalizedCandle] = {}
        async with websockets.connect(self.endpoint, ping_interval=20, ping_timeout=20) as ws:
            request = {
                "method": "subscribe",
                "params": {
                    "channel": "ohlc",
                    "symbol": self.symbols,
                    "interval": self.interval_minutes,
                    "snapshot": True,
                },
                "req_id": 1,
            }
            await ws.send(json.dumps(request))

            while not self._stopped:
                raw = await ws.recv()
                message = json.loads(raw, parse_float=Decimal)

                if message.get("method") == "subscribe" and message.get("success") is False:
                    raise KrakenFeedError(message.get("error", "Kraken subscription failed"))
                if message.get("channel") != "ohlc":
                    continue

                events = sorted(
                    message.get("data", []),
                    key=lambda item: (item.get("symbol", ""), item.get("interval_begin", "")),
                )
                for item in events:
                    symbol = str(item["symbol"])
                    begin = _parse_rfc3339(str(item["interval_begin"]))
                    close_time = begin + timedelta(minutes=self.interval_minutes)
                    candidate = NormalizedCandle(
                        symbol=symbol,
                        venue="KRAKEN_SPOT",
                        timeframe=f"{self.interval_minutes}m",
                        open_time=begin,
                        close_time=close_time,
                        open=Decimal(str(item["open"])),
                        high=Decimal(str(item["high"])),
                        low=Decimal(str(item["low"])),
                        close=Decimal(str(item["close"])),
                        volume=Decimal(str(item.get("volume", 0))),
                        closed=False,
                    )

                    previous = latest.get(symbol)
                    if previous is None:
                        latest[symbol] = candidate
                        continue
                    if candidate.open_time == previous.open_time:
                        latest[symbol] = candidate
                        continue
                    if candidate.open_time < previous.open_time:
                        continue

                    latest[symbol] = candidate
                    yield previous.model_copy(update={"closed": True})
