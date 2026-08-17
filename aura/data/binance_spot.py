from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from aura.data.live_plane import DataDomain, LiveDataEvent
from aura.domain.models import NormalizedCandle


class BinanceStreamError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class BinanceParsedMessage:
    events: tuple[LiveDataEvent, ...] = ()
    closed_candle: NormalizedCandle | None = None


@dataclass(slots=True, frozen=True)
class BinanceDepthUpdate:
    symbol: str
    first_update_id: int
    final_update_id: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    event_time: datetime


class BinanceDepthSequenceGuard:
    """Validate Binance diff-depth continuity after a REST snapshot is seeded."""

    def __init__(self) -> None:
        self.last_update_id: int | None = None

    def seed_snapshot(self, last_update_id: int) -> None:
        if last_update_id < 0:
            raise ValueError("snapshot last_update_id cannot be negative")
        self.last_update_id = last_update_id

    def apply(self, update: BinanceDepthUpdate) -> bool:
        if self.last_update_id is None:
            raise BinanceStreamError("depth guard requires REST snapshot before updates")
        if update.final_update_id <= self.last_update_id:
            return False
        if update.first_update_id > self.last_update_id + 1:
            raise BinanceStreamError(
                "Binance depth sequence gap detected; discard local book and resync snapshot"
            )
        if not update.first_update_id <= self.last_update_id + 1 <= update.final_update_id:
            raise BinanceStreamError("Binance depth update does not bridge current snapshot sequence")
        self.last_update_id = update.final_update_id
        return True


def parse_binance_spot_message(
    message: dict[str, Any],
    *,
    received_at: datetime,
    source_prefix: str = "binance-spot",
) -> BinanceParsedMessage:
    """Normalize Binance Spot/live-testnet stream payloads into AURA data models."""

    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    raw = message.get("data", message)
    if not isinstance(raw, dict):
        raise BinanceStreamError("Binance stream payload must be an object")

    event_type = raw.get("e")
    if event_type in {"trade", "aggTrade"}:
        return BinanceParsedMessage(
            events=(_trade_event(raw, received_at=received_at, source_prefix=source_prefix),)
        )
    if event_type == "depthUpdate":
        update = parse_binance_depth_update(raw)
        return BinanceParsedMessage(
            events=(
                LiveDataEvent(
                    event_id=(
                        f"{source_prefix}:depth:{update.symbol}:{update.first_update_id}:"
                        f"{update.final_update_id}"
                    ),
                    source_id=f"{source_prefix}:depth",
                    domain=DataDomain.ORDER_BOOK,
                    subject=update.symbol,
                    observed_at=update.event_time,
                    received_at=received_at,
                    payload={
                        "first_update_id": update.first_update_id,
                        "final_update_id": update.final_update_id,
                        "bids": [[str(price), str(quantity)] for price, quantity in update.bids],
                        "asks": [[str(price), str(quantity)] for price, quantity in update.asks],
                    },
                    sequence=update.final_update_id,
                ),
            )
        )
    if event_type == "kline":
        return _parse_kline(raw, received_at=received_at, source_prefix=source_prefix)
    if event_type == "serverShutdown":
        event_time = _millis(int(raw["E"]))
        return BinanceParsedMessage(
            events=(
                LiveDataEvent(
                    event_id=f"{source_prefix}:server-shutdown:{int(raw['E'])}",
                    source_id=source_prefix,
                    domain=DataDomain.EXECUTION,
                    subject="BINANCE_SPOT",
                    observed_at=event_time,
                    received_at=received_at,
                    payload={"event": "server_shutdown"},
                ),
            )
        )

    if {"u", "s", "b", "B", "a", "A"}.issubset(raw):
        symbol = str(raw["s"])
        update_id = int(raw["u"])
        return BinanceParsedMessage(
            events=(
                LiveDataEvent(
                    event_id=f"{source_prefix}:book-ticker:{symbol}:{update_id}",
                    source_id=f"{source_prefix}:book-ticker",
                    domain=DataDomain.ORDER_BOOK,
                    subject=symbol,
                    observed_at=received_at,
                    received_at=received_at,
                    payload={
                        "update_id": update_id,
                        "best_bid_price": str(raw["b"]),
                        "best_bid_quantity": str(raw["B"]),
                        "best_ask_price": str(raw["a"]),
                        "best_ask_quantity": str(raw["A"]),
                    },
                    sequence=update_id,
                ),
            )
        )

    raise BinanceStreamError(f"unsupported Binance Spot stream event: {event_type!r}")


def parse_binance_depth_update(raw: dict[str, Any]) -> BinanceDepthUpdate:
    if raw.get("e") != "depthUpdate":
        raise BinanceStreamError("payload is not a Binance depthUpdate")
    return BinanceDepthUpdate(
        symbol=str(raw["s"]),
        first_update_id=int(raw["U"]),
        final_update_id=int(raw["u"]),
        bids=_levels(raw.get("b", [])),
        asks=_levels(raw.get("a", [])),
        event_time=_millis(int(raw["E"])),
    )


def _trade_event(
    raw: dict[str, Any],
    *,
    received_at: datetime,
    source_prefix: str,
) -> LiveDataEvent:
    symbol = str(raw["s"])
    trade_id = int(raw.get("t", raw.get("a")))
    event_time = _millis(int(raw.get("T", raw["E"])))
    return LiveDataEvent(
        event_id=f"{source_prefix}:{raw['e']}:{symbol}:{trade_id}",
        source_id=f"{source_prefix}:trades",
        domain=DataDomain.MARKET_TICK,
        subject=symbol,
        observed_at=event_time,
        received_at=received_at,
        payload={
            "event_type": raw["e"],
            "trade_id": trade_id,
            "price": str(raw["p"]),
            "quantity": str(raw["q"]),
            "buyer_is_market_maker": bool(raw["m"]),
        },
        sequence=trade_id,
    )


def _parse_kline(
    raw: dict[str, Any],
    *,
    received_at: datetime,
    source_prefix: str,
) -> BinanceParsedMessage:
    kline = raw.get("k")
    if not isinstance(kline, dict):
        raise BinanceStreamError("Binance kline event missing k object")
    symbol = str(kline.get("s", raw["s"]))
    interval = str(kline["i"])
    event_time = _millis(int(raw["E"]))
    payload = {
        "interval": interval,
        "open_time_ms": int(kline["t"]),
        "close_time_ms": int(kline["T"]),
        "open": str(kline["o"]),
        "high": str(kline["h"]),
        "low": str(kline["l"]),
        "close": str(kline["c"]),
        "volume": str(kline["v"]),
        "trades": int(kline["n"]),
        "closed": bool(kline["x"]),
        "quote_volume": str(kline["q"]),
        "taker_buy_base_volume": str(kline["V"]),
        "taker_buy_quote_volume": str(kline["Q"]),
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    event = LiveDataEvent(
        event_id=f"{source_prefix}:kline:{symbol}:{interval}:{fingerprint}",
        source_id=f"{source_prefix}:kline:{interval}",
        domain=DataDomain.CANDLE,
        subject=symbol,
        observed_at=event_time,
        received_at=received_at,
        payload=payload,
    )
    if not bool(kline["x"]):
        return BinanceParsedMessage(events=(event,), closed_candle=None)

    candle = NormalizedCandle(
        symbol=symbol,
        venue="BINANCE_SPOT",
        timeframe=interval,
        open_time=_millis(int(kline["t"])),
        close_time=_millis(int(kline["T"])),
        open=Decimal(str(kline["o"])),
        high=Decimal(str(kline["h"])),
        low=Decimal(str(kline["l"])),
        close=Decimal(str(kline["c"])),
        volume=Decimal(str(kline["v"])),
        closed=True,
    )
    return BinanceParsedMessage(events=(event,), closed_candle=candle)


def _levels(raw_levels: Any) -> tuple[tuple[Decimal, Decimal], ...]:
    if not isinstance(raw_levels, list):
        raise BinanceStreamError("Binance depth levels must be an array")
    levels: list[tuple[Decimal, Decimal]] = []
    for level in raw_levels:
        if not isinstance(level, list) or len(level) < 2:
            raise BinanceStreamError("Binance depth level must contain price and quantity")
        levels.append((Decimal(str(level[0])), Decimal(str(level[1]))))
    return tuple(levels)


def _millis(value: int) -> datetime:
    if value < 0:
        raise BinanceStreamError("Binance timestamp cannot be negative")
    return datetime.fromtimestamp(value / 1000.0, tz=UTC)
