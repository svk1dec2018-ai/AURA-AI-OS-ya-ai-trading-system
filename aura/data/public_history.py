from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, ClassVar, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from aura.domain.models import NormalizedCandle


class PublicHistoryError(RuntimeError):
    """A failure at a no-key public historical market-data boundary."""


class PublicHistoryClient(Protocol):
    supported_timeframes: frozenset[str]

    async def fetch_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int,
        end: datetime | None = None,
    ) -> tuple[NormalizedCandle, ...]: ...


JsonTransport = Callable[[str], Any]


def _json_get(url: str, *, timeout_seconds: float = 15.0) -> Any:
    request = Request(
        url,
        headers={"User-Agent": "AURA-AI-OS/0.1 public-history"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise PublicHistoryError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise PublicHistoryError(f"network error: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise PublicHistoryError("provider returned invalid JSON") from exc


def _aware_utc(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("historical candle end must be timezone-aware")
    return result.astimezone(UTC)


def _decimal(value: Any, name: str, *, allow_zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PublicHistoryError(f"invalid {name}: {value!r}") from exc
    if parsed < 0 or (not allow_zero and parsed == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise PublicHistoryError(f"{name} must be {qualifier}")
    return parsed


def _dedupe_closed(
    candles: list[NormalizedCandle],
    *,
    end: datetime,
    limit: int,
) -> tuple[NormalizedCandle, ...]:
    by_open = {
        candle.open_time: candle
        for candle in candles
        if candle.closed and candle.close_time <= end
    }
    ordered = sorted(by_open.values(), key=lambda item: item.open_time)
    return tuple(ordered[-limit:])


class CoinbaseExchangeHistoryClient:
    """No-key Coinbase Exchange candle client.

    Coinbase documents a maximum of 300 buckets and warns that intervals without
    trades may be absent. The client therefore preserves gaps instead of inventing
    synthetic candles.
    """

    endpoint = "https://api.exchange.coinbase.com"
    granularities: ClassVar[dict[str, int]] = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "1d": 86400,
    }
    supported_timeframes = frozenset(granularities)

    def __init__(self, transport: JsonTransport = _json_get) -> None:
        self.transport = transport

    async def fetch_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int = 300,
        end: datetime | None = None,
    ) -> tuple[NormalizedCandle, ...]:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("Coinbase symbol cannot be empty")
        if timeframe not in self.granularities:
            raise ValueError(f"unsupported Coinbase historical timeframe: {timeframe}")
        if not 1 <= limit <= 300:
            raise ValueError("Coinbase candle limit must be between 1 and 300")
        end_at = _aware_utc(end)
        seconds = self.granularities[timeframe]
        start_at = end_at - timedelta(seconds=seconds * limit)
        params = urlencode(
            {
                "granularity": seconds,
                "start": start_at.isoformat().replace("+00:00", "Z"),
                "end": end_at.isoformat().replace("+00:00", "Z"),
            }
        )
        url = f"{self.endpoint}/products/{normalized_symbol}/candles?{params}"
        payload = await asyncio.to_thread(self.transport, url)
        if not isinstance(payload, list):
            raise PublicHistoryError("Coinbase candle response must be a list")

        candles: list[NormalizedCandle] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                raise PublicHistoryError("invalid Coinbase candle row")
            try:
                open_at = datetime.fromtimestamp(int(row[0]), tz=UTC)
            except (TypeError, ValueError, OSError) as exc:
                raise PublicHistoryError(f"invalid Coinbase candle time: {row[0]!r}") from exc
            candles.append(
                NormalizedCandle(
                    symbol=normalized_symbol,
                    venue="COINBASE_PUBLIC",
                    timeframe=timeframe,
                    open_time=open_at,
                    close_time=open_at + timedelta(seconds=seconds),
                    low=_decimal(row[1], "Coinbase low"),
                    high=_decimal(row[2], "Coinbase high"),
                    open=_decimal(row[3], "Coinbase open"),
                    close=_decimal(row[4], "Coinbase close"),
                    volume=_decimal(row[5], "Coinbase volume", allow_zero=True),
                    closed=True,
                )
            )
        return _dedupe_closed(candles, end=end_at, limit=limit)


class BybitSpotHistoryClient:
    """No-key Bybit v5 spot kline client."""

    endpoint = "https://api.bybit.com/v5/market/kline"
    intervals: ClassVar[dict[str, str]] = {
        "1m": "1",
        "3m": "3",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "2h": "120",
        "4h": "240",
        "6h": "360",
        "12h": "720",
        "1d": "D",
        "1w": "W",
    }
    durations: ClassVar[dict[str, timedelta]] = {
        "1m": timedelta(minutes=1),
        "3m": timedelta(minutes=3),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "2h": timedelta(hours=2),
        "4h": timedelta(hours=4),
        "6h": timedelta(hours=6),
        "12h": timedelta(hours=12),
        "1d": timedelta(days=1),
        "1w": timedelta(days=7),
    }
    supported_timeframes = frozenset(intervals)

    def __init__(self, transport: JsonTransport = _json_get) -> None:
        self.transport = transport

    async def fetch_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
        end: datetime | None = None,
    ) -> tuple[NormalizedCandle, ...]:
        normalized_symbol = symbol.replace("-", "").strip().upper()
        if not normalized_symbol:
            raise ValueError("Bybit symbol cannot be empty")
        if timeframe not in self.intervals:
            raise ValueError(f"unsupported Bybit historical timeframe: {timeframe}")
        if not 1 <= limit <= 1000:
            raise ValueError("Bybit candle limit must be between 1 and 1000")
        end_at = _aware_utc(end)
        params = urlencode(
            {
                "category": "spot",
                "symbol": normalized_symbol,
                "interval": self.intervals[timeframe],
                "end": int(end_at.timestamp() * 1000),
                "limit": limit,
            }
        )
        payload = await asyncio.to_thread(self.transport, f"{self.endpoint}?{params}")
        if not isinstance(payload, dict) or payload.get("retCode") != 0:
            message = payload.get("retMsg") if isinstance(payload, dict) else None
            raise PublicHistoryError(f"Bybit kline request failed: {message or 'invalid response'}")
        result = payload.get("result")
        rows = result.get("list") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise PublicHistoryError("Bybit kline response is missing result.list")

        candles: list[NormalizedCandle] = []
        duration = self.durations[timeframe]
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                raise PublicHistoryError("invalid Bybit kline row")
            try:
                open_at = datetime.fromtimestamp(int(row[0]) / 1000.0, tz=UTC)
            except (TypeError, ValueError, OSError) as exc:
                raise PublicHistoryError(f"invalid Bybit kline time: {row[0]!r}") from exc
            candles.append(
                NormalizedCandle(
                    symbol=normalized_symbol,
                    venue="BYBIT_PUBLIC",
                    timeframe=timeframe,
                    open_time=open_at,
                    close_time=open_at + duration,
                    open=_decimal(row[1], "Bybit open"),
                    high=_decimal(row[2], "Bybit high"),
                    low=_decimal(row[3], "Bybit low"),
                    close=_decimal(row[4], "Bybit close"),
                    volume=_decimal(row[5], "Bybit volume", allow_zero=True),
                    closed=True,
                )
            )
        return _dedupe_closed(candles, end=end_at, limit=limit)


class HistoricalCandleArchive:
    """Atomic, de-duplicated JSONL archive for normalized public candles."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def merge(self, candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle]) -> int:
        if not candles:
            return 0
        keys = {(item.symbol, item.timeframe) for item in candles}
        if len(keys) != 1:
            raise ValueError("archive merge requires one symbol/timeframe series")
        if any(not item.closed for item in candles):
            raise ValueError("archive accepts only closed candles")
        symbol, timeframe = next(iter(keys))
        existing = self.read(symbol=symbol, timeframe=timeframe)
        by_open = {item.open_time: item for item in existing}
        before = len(by_open)
        by_open.update({item.open_time: item for item in candles})
        ordered = tuple(sorted(by_open.values(), key=lambda item: item.open_time))
        path = self.path_for(symbol=symbol, timeframe=timeframe)
        temp = path.with_suffix(".tmp")
        temp.write_text(
            "".join(item.model_dump_json() + "\n" for item in ordered),
            encoding="utf-8",
        )
        temp.replace(path)
        return len(by_open) - before

    def read(self, *, symbol: str, timeframe: str) -> tuple[NormalizedCandle, ...]:
        path = self.path_for(symbol=symbol, timeframe=timeframe)
        if not path.exists():
            return ()
        candles: list[NormalizedCandle] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                candles.append(NormalizedCandle.model_validate_json(line))
            except Exception as exc:
                raise RuntimeError(f"invalid historical candle at {path}:{line_number}: {exc}") from exc
        return tuple(sorted(candles, key=lambda item: item.open_time))

    def path_for(self, *, symbol: str, timeframe: str) -> Path:
        safe_symbol = re.sub(r"[^A-Z0-9_.-]+", "_", symbol.upper())
        safe_timeframe = re.sub(r"[^A-Za-z0-9_.-]+", "_", timeframe)
        return self.root / f"{safe_symbol}__{safe_timeframe}.jsonl"
