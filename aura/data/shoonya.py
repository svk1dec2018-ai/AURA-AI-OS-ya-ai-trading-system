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

SHOONYA_REST_URL = "https://api.shoonya.com/NorenWClientTP"
SHOONYA_WEBSOCKET_URL = "wss://api.shoonya.com/NorenWSTP/"
_INDIA_TZ = ZoneInfo("Asia/Kolkata")


class ShoonyaError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class ShoonyaSessionCredentials:
    """Runtime session only; login password/TOTP never need to enter AURA state."""

    user_id: str
    account_id: str
    session_token: str

    def __post_init__(self) -> None:
        if not self.user_id or not self.account_id or not self.session_token:
            raise ValueError("Shoonya user/account/session token are required")


def load_shoonya_session_from_env() -> ShoonyaSessionCredentials:
    values = {
        "user_id": os.environ.get("AURA_SHOONYA_USER_ID", "").strip(),
        "account_id": os.environ.get("AURA_SHOONYA_ACCOUNT_ID", "").strip(),
        "session_token": os.environ.get("AURA_SHOONYA_SESSION_TOKEN", "").strip(),
    }
    if not all(values.values()):
        raise RuntimeError(
            "set AURA_SHOONYA_USER_ID, AURA_SHOONYA_ACCOUNT_ID and "
            "AURA_SHOONYA_SESSION_TOKEN"
        )
    return ShoonyaSessionCredentials(**values)


@dataclass(slots=True, frozen=True)
class ShoonyaSubscription:
    exchange: str
    token: str
    symbol: str

    def __post_init__(self) -> None:
        if not self.exchange or not self.token or not self.symbol:
            raise ValueError("Shoonya subscription fields cannot be empty")
        if "|" in self.exchange or "#" in self.exchange or "#" in self.token:
            raise ValueError("Shoonya subscription contains protocol delimiter")

    @property
    def key(self) -> str:
        return f"{self.exchange}|{self.token}"


class _SlidingWindowRateGate:
    def __init__(self, *, per_second: int, per_minute: int) -> None:
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
                second_wait = (
                    max(0.0, 1.0 - (now - self._events[-self.per_second]))
                    if len(self._events) >= self.per_second
                    else 0.0
                )
                minute_wait = (
                    max(0.0, 60.0 - (now - self._events[0]))
                    if len(self._events) >= self.per_minute
                    else 0.0
                )
                delay = max(0.01, min(value for value in (second_wait, minute_wait) if value > 0))
            time_module.sleep(delay)


class ShoonyaRestMarketDataClient:
    """Read-only Shoonya REST data using an already authenticated session token."""

    def __init__(
        self,
        credentials: ShoonyaSessionCredentials,
        *,
        timeout_seconds: float = 15.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds
        self._quote_gate = _SlidingWindowRateGate(per_second=10, per_minute=200)
        self._general_gate = _SlidingWindowRateGate(per_second=40, per_minute=200)

    def get_quotes(self, *, exchange: str, token: str) -> dict:
        self._quote_gate.wait()
        return self._post(
            "/GetQuotes",
            {"uid": self.credentials.user_id, "exch": exchange, "token": token},
            rate_limited=False,
        )

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
        if interval_minutes not in {1, 3, 5, 10, 15, 30, 60, 120, 240}:
            raise ValueError("unsupported Shoonya interval")
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
            raise ShoonyaError("Shoonya TPSeries returned a non-list response")
        return normalize_shoonya_time_price_series(
            payload,
            symbol=symbol,
            interval_minutes=interval_minutes,
            as_of=decision_time,
        )

    def _post(self, route: str, payload: dict, *, rate_limited: bool = True):
        if rate_limited:
            self._general_gate.wait()
        body = urlencode(
            {
                "jData": json.dumps(payload, separators=(",", ":")),
                "jKey": self.credentials.session_token,
            }
        ).encode("utf-8")
        request = Request(
            SHOONYA_REST_URL + route,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "AURA-AI-OS/0.1 shoonya-data",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ShoonyaError(f"Shoonya HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ShoonyaError(f"Shoonya network error: {exc.reason}") from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ShoonyaError("Shoonya returned invalid JSON") from exc
        if isinstance(parsed, dict) and parsed.get("stat") == "Not_Ok":
            raise ShoonyaError(f"Shoonya API failure: {parsed.get('emsg', parsed)}")
        return parsed


@dataclass(slots=True)
class _ShoonyaTouchlineState:
    last_price: Decimal | None = None
    cumulative_volume: Decimal | None = None


class ShoonyaTouchlineNormalizer:
    """Merge Shoonya tk/tf delta packets without fabricating absent fields."""

    def __init__(self, subscriptions: Iterable[ShoonyaSubscription]) -> None:
        items = tuple(subscriptions)
        self._symbol_by_key = {item.key: item.symbol for item in items}
        if len(self._symbol_by_key) != len(items):
            raise ValueError("duplicate Shoonya exchange/token subscriptions")
        self._state: dict[str, _ShoonyaTouchlineState] = {}

    def normalize(
        self,
        message: dict,
        *,
        received_at: datetime,
    ) -> CanonicalTradeTick | None:
        _require_aware(received_at, "received_at")
        if message.get("t") not in {"tk", "tf"}:
            return None
        exchange = str(message.get("e") or "")
        token = str(message.get("tk") or "")
        key = f"{exchange}|{token}"
        symbol = self._symbol_by_key.get(key)
        if symbol is None:
            return None
        state = self._state.setdefault(key, _ShoonyaTouchlineState())

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

        observed_at = _feed_timestamp(message, fallback=received_at)
        return CanonicalTradeTick(
            symbol=symbol,
            venue="SHOONYA_LIVE",
            price=state.last_price,
            quantity=quantity,
            timestamp=observed_at,
        )


class ShoonyaLiveTickerSource:
    """Single reconnecting Shoonya WebSocket with automatic resubscription."""

    def __init__(
        self,
        credentials: ShoonyaSessionCredentials,
        subscriptions: Iterable[ShoonyaSubscription],
        *,
        reconnect_initial_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
        heartbeat_seconds: float = 3.0,
    ) -> None:
        self.credentials = credentials
        self.subscriptions = tuple(subscriptions)
        if not self.subscriptions:
            raise ValueError("Shoonya live source needs at least one subscription")
        if reconnect_initial_seconds <= 0 or reconnect_max_seconds < reconnect_initial_seconds:
            raise ValueError("invalid Shoonya reconnect policy")
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self.reconnect_initial_seconds = reconnect_initial_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.normalizer = ShoonyaTouchlineNormalizer(self.subscriptions)
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def ticks(self) -> AsyncIterator[CanonicalTradeTick]:
        backoff = self.reconnect_initial_seconds
        while not self._stopped:
            try:
                async with websockets.connect(
                    SHOONYA_WEBSOCKET_URL,
                    ping_interval=None,
                    close_timeout=5,
                ) as socket:
                    await socket.send(
                        json.dumps(
                            {
                                "t": "c",
                                "uid": self.credentials.user_id,
                                "actid": self.credentials.account_id,
                                "susertoken": self.credentials.session_token,
                                "source": "API",
                            },
                            separators=(",", ":"),
                        )
                    )
                    await self._await_connection_ack(socket)
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
                await asyncio.sleep(backoff)
                backoff = min(self.reconnect_max_seconds, backoff * 2)
                if isinstance(exc, ShoonyaError) and "authentication" in str(exc).lower():
                    raise

    async def _await_connection_ack(self, socket) -> None:
        while True:
            raw = await asyncio.wait_for(socket.recv(), timeout=10.0)
            message = _decode_message(raw)
            if message.get("t") != "ck":
                continue
            status = str(message.get("s") or message.get("stat") or "").lower()
            if status and status not in {"ok", "success"}:
                raise ShoonyaError(f"Shoonya WebSocket authentication failed: {message}")
            return


def normalize_shoonya_time_price_series(
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
                venue="SHOONYA_LIVE",
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
    deduped = {candle.open_time: candle for candle in candles}
    return tuple(deduped[key] for key in sorted(deduped))


def _series_open_time(row: dict) -> datetime:
    raw_epoch = row.get("ssboe")
    if raw_epoch not in {None, ""}:
        try:
            return datetime.fromtimestamp(int(raw_epoch), tz=UTC)
        except (TypeError, ValueError, OSError) as exc:
            raise ShoonyaError(f"invalid Shoonya ssboe: {raw_epoch!r}") from exc
    raw_time = str(row.get("time") or "").strip()
    for pattern in ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            local = datetime.strptime(raw_time, pattern).replace(tzinfo=_INDIA_TZ)
            return local.astimezone(UTC)
        except ValueError:
            continue
    raise ShoonyaError(f"invalid Shoonya candle time: {raw_time!r}")


def _feed_timestamp(message: dict, *, fallback: datetime) -> datetime:
    raw = message.get("ft") or message.get("exch_tm")
    if raw in {None, ""}:
        return fallback.astimezone(UTC)
    text = str(raw).strip()
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text), tz=UTC)
        except (ValueError, OSError):
            return fallback.astimezone(UTC)
    for pattern in ("%d-%m-%Y %H:%M:%S", "%H:%M:%S %d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=_INDIA_TZ).astimezone(UTC)
        except ValueError:
            continue
    return fallback.astimezone(UTC)


def _decode_message(raw) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ShoonyaError("Shoonya WebSocket returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ShoonyaError("Shoonya WebSocket returned non-object JSON")
    return parsed


def _positive_decimal(value, name: str) -> Decimal:
    result = _decimal(value, name)
    if result <= 0:
        raise ShoonyaError(f"Shoonya {name} must be positive")
    return result


def _nonnegative_decimal(value, name: str) -> Decimal:
    result = _decimal(value, name)
    if result < 0:
        raise ShoonyaError(f"Shoonya {name} cannot be negative")
    return result


def _decimal(value, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ShoonyaError(f"invalid Shoonya {name}: {value!r}") from exc


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
