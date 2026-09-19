from __future__ import annotations

import asyncio
import json
import os
import time as time_module
from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import websockets

from aura.data.candle_aggregation import CanonicalTradeTick
from aura.domain.models import NormalizedCandle

FLATTRADE_REST_URL = "https://piconnect.flattrade.in/PiConnectAPI"
FLATTRADE_WEBSOCKET_URL = "wss://piconnect.flattrade.in/PiConnectWSAPI/"
_INDIA_TZ = ZoneInfo("Asia/Kolkata")


class FlattradeError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class FlattradeSessionCredentials:
    user_id: str
    account_id: str
    access_token: str

    def __post_init__(self) -> None:
        if not self.user_id or not self.account_id or not self.access_token:
            raise ValueError("Flattrade user/account/access token are required")


def load_flattrade_session_from_env() -> FlattradeSessionCredentials:
    values = {
        "user_id": os.environ.get("AURA_FLATTRADE_USER_ID", "").strip(),
        "account_id": os.environ.get("AURA_FLATTRADE_ACCOUNT_ID", "").strip(),
        "access_token": os.environ.get("AURA_FLATTRADE_ACCESS_TOKEN", "").strip(),
    }
    if not all(values.values()):
        raise RuntimeError(
            "set AURA_FLATTRADE_USER_ID, AURA_FLATTRADE_ACCOUNT_ID and "
            "AURA_FLATTRADE_ACCESS_TOKEN"
        )
    return FlattradeSessionCredentials(**values)


@dataclass(slots=True, frozen=True)
class FlattradeSubscription:
    exchange: str
    token: str
    symbol: str

    def __post_init__(self) -> None:
        if not self.exchange or not self.token or not self.symbol:
            raise ValueError("Flattrade subscription fields cannot be empty")
        if "#" in self.exchange or "|" in self.exchange or "#" in self.token:
            raise ValueError("Flattrade subscription contains protocol delimiter")

    @property
    def key(self) -> str:
        return f"{self.exchange}|{self.token}"


class _RateGate:
    def __init__(self, *, per_second: int = 40, per_minute: int = 200) -> None:
        if per_second <= 0 or per_minute <= 0:
            raise ValueError("rate limits must be positive")
        self.per_second = per_second
        self.per_minute = per_minute
        self._events: deque[float] = deque()
        self._lock = Lock()

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time_module.monotonic()
                while self._events and now - self._events[0] >= 60.0:
                    self._events.popleft()
                recent_second = sum(now - item < 1.0 for item in self._events)
                if recent_second < self.per_second and len(self._events) < self.per_minute:
                    self._events.append(now)
                    return
                delays: list[float] = []
                if len(self._events) >= self.per_minute:
                    delays.append(max(0.01, 60.0 - (now - self._events[0])))
                if recent_second >= self.per_second:
                    second_window = [item for item in self._events if now - item < 1.0]
                    if second_window:
                        delays.append(max(0.01, 1.0 - (now - second_window[0])))
                delay = min(delays) if delays else 0.01
            time_module.sleep(delay)


class FlattradeRestMarketDataClient:
    """Read-only Pi v2 chart data using the current REST base endpoint."""

    def __init__(
        self,
        credentials: FlattradeSessionCredentials,
        *,
        timeout_seconds: float = 15.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds
        self._gate = _RateGate()

    def get_time_price_series(
        self,
        *,
        exchange: str,
        token: str,
        start_time: datetime,
        end_time: datetime,
        interval_minutes: int = 1,
        symbol: str,
        as_of: datetime | None = None,
    ) -> tuple[NormalizedCandle, ...]:
        if interval_minutes not in {1, 3, 5, 10, 15, 30, 60, 120}:
            raise ValueError("unsupported Flattrade interval")
        _require_aware(start_time, "start_time")
        _require_aware(end_time, "end_time")
        decision_time = as_of or datetime.now(UTC)
        _require_aware(decision_time, "as_of")
        if end_time <= start_time:
            raise ValueError("end_time must be after start_time")
        payload = self._post(
            "/TPSeries",
            {
                "uid": self.credentials.user_id,
                "exch": exchange,
                "token": token,
                "st": str(int(start_time.timestamp())),
                "et": str(int(end_time.timestamp())),
                "intrv": str(interval_minutes),
            },
        )
        if not isinstance(payload, list):
            raise FlattradeError("Flattrade TPSeries returned a non-list response")
        return normalize_flattrade_time_price_series(
            payload,
            symbol=symbol,
            interval_minutes=interval_minutes,
            as_of=decision_time,
        )

    def _post(self, route: str, payload: dict):
        self._gate.wait()
        body = urlencode(
            {
                "jData": json.dumps(payload, separators=(",", ":")),
                "jKey": self.credentials.access_token,
            }
        ).encode()
        request = Request(
            FLATTRADE_REST_URL + route,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "AURA-AI-OS/0.1 flattrade-data",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode()
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise FlattradeError(f"Flattrade HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise FlattradeError(f"Flattrade network error: {exc.reason}") from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FlattradeError("Flattrade returned invalid JSON") from exc
        if isinstance(parsed, dict) and parsed.get("stat") == "Not_Ok":
            raise FlattradeError(f"Flattrade API failure: {parsed.get('emsg', parsed)}")
        return parsed


@dataclass(slots=True)
class _TouchlineState:
    last_price: Decimal | None = None
    cumulative_volume: Decimal | None = None


class FlattradeTouchlineNormalizer:
    def __init__(self, subscriptions: Iterable[FlattradeSubscription]) -> None:
        items = tuple(subscriptions)
        self._symbol_by_key = {item.key: item.symbol for item in items}
        if len(self._symbol_by_key) != len(items):
            raise ValueError("duplicate Flattrade exchange/token subscriptions")
        self._state: dict[str, _TouchlineState] = {}

    def normalize(
        self,
        message: dict,
        *,
        received_at: datetime,
    ) -> CanonicalTradeTick | None:
        _require_aware(received_at, "received_at")
        if message.get("t") not in {"tk", "tf"}:
            return None
        key = f"{message.get('e', '')}|{message.get('tk', '')}"
        symbol = self._symbol_by_key.get(key)
        if symbol is None:
            return None
        state = self._state.setdefault(key, _TouchlineState())
        price_changed = "lp" in message
        volume_changed = "v" in message
        if price_changed:
            state.last_price = _positive_decimal(message["lp"], "lp")
        if state.last_price is None:
            return None
        quantity = Decimal(0)
        if volume_changed:
            cumulative = _nonnegative_decimal(message["v"], "v")
            if state.cumulative_volume is not None and cumulative >= state.cumulative_volume:
                quantity = cumulative - state.cumulative_volume
            state.cumulative_volume = cumulative
        if not price_changed and not volume_changed:
            return None
        return CanonicalTradeTick(
            symbol=symbol,
            venue="FLATTRADE_LIVE",
            price=state.last_price,
            quantity=quantity,
            timestamp=_feed_timestamp(message, fallback=received_at),
        )


class FlattradeLiveTickerSource:
    """Pi v2 touchline stream with current auth payload and resubscription."""

    def __init__(
        self,
        credentials: FlattradeSessionCredentials,
        subscriptions: Iterable[FlattradeSubscription],
        *,
        reconnect_initial_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
        heartbeat_seconds: float = 30.0,
    ) -> None:
        self.credentials = credentials
        self.subscriptions = tuple(subscriptions)
        if not self.subscriptions:
            raise ValueError("Flattrade live source needs at least one subscription")
        if reconnect_initial_seconds <= 0 or reconnect_max_seconds < reconnect_initial_seconds:
            raise ValueError("invalid Flattrade reconnect policy")
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self.reconnect_initial_seconds = reconnect_initial_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.normalizer = FlattradeTouchlineNormalizer(self.subscriptions)
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def ticks(self) -> AsyncIterator[CanonicalTradeTick]:
        backoff = self.reconnect_initial_seconds
        while not self._stopped:
            try:
                async with websockets.connect(
                    FLATTRADE_WEBSOCKET_URL,
                    ping_interval=None,
                    close_timeout=5,
                ) as socket:
                    await socket.send(
                        json.dumps(
                            {
                                "t": "a",
                                "uid": self.credentials.user_id,
                                "actid": self.credentials.account_id,
                                "source": "API",
                                "accesstoken": self.credentials.access_token,
                            },
                            separators=(",", ":"),
                        )
                    )
                    await self._await_ack(socket)
                    await socket.send(
                        json.dumps(
                            {"t": "t", "k": "#".join(item.key for item in self.subscriptions)},
                            separators=(",", ":"),
                        )
                    )
                    backoff = self.reconnect_initial_seconds
                    while not self._stopped:
                        try:
                            raw = await asyncio.wait_for(
                                socket.recv(), timeout=self.heartbeat_seconds
                            )
                        except TimeoutError:
                            await socket.send('{"t":"h"}')
                            continue
                        message = _decode_message(raw)
                        tick = self.normalizer.normalize(
                            message,
                            received_at=datetime.now(UTC),
                        )
                        if tick is not None:
                            yield tick
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stopped:
                    return
                if isinstance(exc, FlattradeError) and "authentication" in str(exc).lower():
                    raise
                await asyncio.sleep(backoff)
                backoff = min(self.reconnect_max_seconds, backoff * 2)

    async def _await_ack(self, socket) -> None:
        while True:
            message = _decode_message(await asyncio.wait_for(socket.recv(), timeout=10.0))
            if message.get("t") != "ak":
                continue
            status = str(message.get("s") or "").lower()
            if status and status != "ok":
                raise FlattradeError(f"Flattrade WebSocket authentication failed: {message}")
            return


def normalize_flattrade_time_price_series(
    rows: list[dict],
    *,
    symbol: str,
    interval_minutes: int,
    as_of: datetime,
) -> tuple[NormalizedCandle, ...]:
    _require_aware(as_of, "as_of")
    duration = timedelta(minutes=interval_minutes)
    candles: list[NormalizedCandle] = []
    for row in rows:
        open_time = _series_open_time(row)
        close_time = open_time + duration
        if close_time > as_of:
            continue
        candles.append(
            NormalizedCandle(
                symbol=symbol,
                venue="FLATTRADE_LIVE",
                timeframe=f"{interval_minutes}m",
                open_time=open_time,
                close_time=close_time,
                open=_positive_decimal(row.get("into"), "into"),
                high=_positive_decimal(row.get("inth"), "inth"),
                low=_positive_decimal(row.get("intl"), "intl"),
                close=_positive_decimal(row.get("intc"), "intc"),
                volume=_nonnegative_decimal(row.get("intv", row.get("v", 0)), "intv"),
                closed=True,
            )
        )
    unique = {item.open_time: item for item in candles}
    return tuple(unique[key] for key in sorted(unique))


def _series_open_time(row: dict) -> datetime:
    raw = str(row.get("time") or "").strip()
    for pattern in ("%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=_INDIA_TZ).astimezone(UTC)
        except ValueError:
            continue
    raise FlattradeError(f"invalid Flattrade candle time: {raw!r}")


def _feed_timestamp(message: dict, *, fallback: datetime) -> datetime:
    raw = str(message.get("ft") or "").strip()
    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw), tz=UTC)
        except (OSError, ValueError):
            pass
    return fallback.astimezone(UTC)


def _decode_message(raw) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise FlattradeError("Flattrade WebSocket returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise FlattradeError("Flattrade WebSocket returned non-object JSON")
    return parsed


def _positive_decimal(value, name: str) -> Decimal:
    result = _decimal(value, name)
    if result <= 0:
        raise FlattradeError(f"Flattrade {name} must be positive")
    return result


def _nonnegative_decimal(value, name: str) -> Decimal:
    result = _decimal(value, name)
    if result < 0:
        raise FlattradeError(f"Flattrade {name} cannot be negative")
    return result


def _decimal(value, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FlattradeError(f"invalid Flattrade {name}: {value!r}") from exc


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
