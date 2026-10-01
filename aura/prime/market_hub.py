from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.data.cross_feed import QuoteObservation
from aura.data.public_crypto_feeds import (
    BybitPublicTickerFeed,
    CoinbasePublicTickerFeed,
    OkxPublicTickerFeed,
)


@dataclass(slots=True, frozen=True)
class PublicQuoteRoute:
    provider: str
    native_symbol: str
    canonical_symbol: str
    market: str


DEFAULT_PUBLIC_CRYPTO_ROUTES: tuple[PublicQuoteRoute, ...] = (
    PublicQuoteRoute("COINBASE_PUBLIC", "BTC-USD", "BTCUSD", "CRYPTO_SPOT"),
    PublicQuoteRoute("COINBASE_PUBLIC", "ETH-USD", "ETHUSD", "CRYPTO_SPOT"),
    PublicQuoteRoute("BYBIT_PUBLIC", "BTCUSDT", "BTCUSDT", "CRYPTO_SPOT"),
    PublicQuoteRoute("BYBIT_PUBLIC", "ETHUSDT", "ETHUSDT", "CRYPTO_SPOT"),
    PublicQuoteRoute("OKX_PUBLIC", "BTC-USDT", "BTCUSDT", "CRYPTO_SPOT"),
    PublicQuoteRoute("OKX_PUBLIC", "ETH-USDT", "ETHUSDT", "CRYPTO_SPOT"),
)


class PrimePublicQuoteHub:
    """Key-free public crypto quote cache for the owner dashboard.

    The hub has no broker credentials and no order/execution methods. Provider
    adapters own reconnect/backoff behavior. A missing feed stays unavailable
    rather than being replaced by fabricated prices.
    """

    def __init__(
        self,
        routes: tuple[PublicQuoteRoute, ...] = DEFAULT_PUBLIC_CRYPTO_ROUTES,
        *,
        stale_after: timedelta = timedelta(seconds=20),
    ) -> None:
        if not routes:
            raise ValueError("public quote hub requires at least one route")
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        self.routes = routes
        self.stale_after = stale_after
        self._route_by_provider_symbol = {
            (route.provider, route.native_symbol): route for route in routes
        }
        if len(self._route_by_provider_symbol) != len(routes):
            raise ValueError("public quote routes must be unique per provider/symbol")
        self._quotes: dict[tuple[str, str], QuoteObservation] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: datetime | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def ingest(self, quote: QuoteObservation) -> None:
        route = self._route_by_provider_symbol.get((quote.provider, quote.symbol))
        if route is None:
            return
        if quote.observed_at > quote.received_at:
            return
        key = (quote.provider, quote.symbol)
        with self._lock:
            previous = self._quotes.get(key)
            if previous is not None and quote.observed_at < previous.observed_at:
                return
            self._quotes[key] = quote

    def snapshot(self, *, now: datetime | None = None) -> dict[str, object]:
        as_of = now or datetime.now(UTC)
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("snapshot time must be timezone-aware")
        with self._lock:
            quotes = dict(self._quotes)
        items: list[dict[str, object]] = []
        for route in self.routes:
            quote = quotes.get((route.provider, route.native_symbol))
            if quote is None:
                items.append(
                    {
                        "provider": route.provider,
                        "native_symbol": route.native_symbol,
                        "symbol": route.canonical_symbol,
                        "market": route.market,
                        "available": False,
                        "stale": True,
                        "execution_authority": False,
                    }
                )
                continue
            age_seconds = max(0.0, (as_of - quote.observed_at).total_seconds())
            items.append(
                {
                    "provider": route.provider,
                    "native_symbol": route.native_symbol,
                    "symbol": route.canonical_symbol,
                    "market": route.market,
                    "available": True,
                    "stale": age_seconds > self.stale_after.total_seconds(),
                    "age_seconds": round(age_seconds, 3),
                    "last": _number(quote.last),
                    "bid": _optional_number(quote.bid),
                    "ask": _optional_number(quote.ask),
                    "observed_at": quote.observed_at.isoformat(),
                    "received_at": quote.received_at.isoformat(),
                    "trust_score": quote.trust_score,
                    "execution_authority": False,
                }
            )
        return {
            "ok": True,
            "mode": "PUBLIC_KEY_FREE_READ_ONLY",
            "running": self.running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "generated_at": as_of.isoformat(),
            "items": items,
            "available_count": sum(bool(item["available"]) for item in items),
            "fresh_count": sum(
                bool(item["available"]) and not bool(item["stale"]) for item in items
            ),
            "execution_authority": False,
        }

    def start_background(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._started_at = datetime.now(UTC)
        self._thread = threading.Thread(
            target=self._thread_main,
            name="aura-prime-public-quotes",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, join_seconds: float = 3.0) -> None:
        if join_seconds < 0:
            raise ValueError("join_seconds cannot be negative")
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_seconds)

    def _thread_main(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        coinbase_symbols = tuple(
            route.native_symbol
            for route in self.routes
            if route.provider == "COINBASE_PUBLIC"
        )
        bybit_symbols = tuple(
            route.native_symbol
            for route in self.routes
            if route.provider == "BYBIT_PUBLIC"
        )
        okx_symbols = tuple(
            route.native_symbol
            for route in self.routes
            if route.provider == "OKX_PUBLIC"
        )
        feeds = []
        if coinbase_symbols:
            feeds.append(CoinbasePublicTickerFeed(coinbase_symbols))
        if bybit_symbols:
            feeds.append(BybitPublicTickerFeed(bybit_symbols, market="spot"))
        if okx_symbols:
            feeds.append(OkxPublicTickerFeed(okx_symbols))

        tasks = [
            asyncio.create_task(self._consume(feed))
            for feed in feeds
        ]
        try:
            while not self._stop.is_set():
                await asyncio.sleep(0.25)
        finally:
            for feed in feeds:
                feed.stop()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _consume(self, feed) -> None:
        async for quote in feed.stream():
            if self._stop.is_set():
                return
            self.ingest(quote)


def _number(value: Decimal) -> float:
    return float(value)


def _optional_number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
