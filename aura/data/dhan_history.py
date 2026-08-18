from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from aura.data.dhan_live_ticker import DhanLiveCredentials
from aura.domain.models import NormalizedCandle
from aura.markets.universe import CanonicalInstrument

DHAN_INTRADAY_HISTORY_URL = "https://api.dhan.co/v2/charts/intraday"
DHAN_HISTORY_INTERVALS = frozenset({1, 5, 15, 25, 60})
DHAN_INSTRUMENT_TYPES = frozenset(
    {
        "INDEX",
        "FUTIDX",
        "OPTIDX",
        "EQUITY",
        "FUTSTK",
        "OPTSTK",
        "FUTCOM",
        "OPTFUT",
        "FUTCUR",
        "OPTCUR",
    }
)
_INDIA_TZ = ZoneInfo("Asia/Kolkata")
_RESAMPLE_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
}


class DhanHistoricalDataError(RuntimeError):
    pass


class DhanIntradayHistoryClient:
    """Point-in-time Dhan intraday candle client used only for causal warm-up.

    The caller supplies Dhan's exact instrument enum from the scrip master. AURA
    intentionally does not guess FUTIDX/FUTSTK/OPTIDX/OPTSTK from a symbol name.
    Only bars fully closed by `as_of` are returned.
    """

    def __init__(
        self,
        credentials: DhanLiveCredentials,
        *,
        timeout_seconds: float = 20.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds

    def fetch(
        self,
        instrument: CanonicalInstrument,
        *,
        dhan_instrument_type: str,
        from_time: datetime,
        to_time: datetime,
        interval_minutes: int = 1,
        include_open_interest: bool = False,
        as_of: datetime | None = None,
    ) -> tuple[NormalizedCandle, ...]:
        instrument_type = dhan_instrument_type.strip().upper()
        if instrument_type not in DHAN_INSTRUMENT_TYPES:
            raise ValueError(f"unsupported Dhan instrument type: {instrument_type}")
        if interval_minutes not in DHAN_HISTORY_INTERVALS:
            raise ValueError(
                f"Dhan intraday interval must be one of {sorted(DHAN_HISTORY_INTERVALS)}"
            )
        _require_aware(from_time, "from_time")
        _require_aware(to_time, "to_time")
        decision_time = as_of or datetime.now(UTC)
        _require_aware(decision_time, "as_of")
        if to_time <= from_time:
            raise ValueError("to_time must be after from_time")
        if to_time - from_time > timedelta(days=90):
            raise ValueError("Dhan intraday request window cannot exceed 90 days")
        if not instrument.segment:
            raise ValueError("Dhan historical instrument requires exchange segment")

        payload = {
            "securityId": instrument.venue_symbol,
            "exchangeSegment": instrument.segment,
            "instrument": instrument_type,
            "interval": str(interval_minutes),
            "oi": bool(include_open_interest),
            "fromDate": _dhan_datetime(from_time),
            "toDate": _dhan_datetime(to_time),
        }
        response = self._post(payload)
        return normalize_dhan_intraday_response(
            response,
            instrument=instrument,
            interval_minutes=interval_minutes,
            as_of=decision_time,
        )

    def _post(self, payload: dict) -> dict:
        request = Request(
            DHAN_INTRADAY_HISTORY_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "access-token": self.credentials.access_token,
                "client-id": self.credentials.client_id,
                "User-Agent": "AURA-AI-OS/0.1 historical-warmup",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise DhanHistoricalDataError(
                f"Dhan intraday history HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise DhanHistoricalDataError(
                f"Dhan intraday history network error: {exc.reason}"
            ) from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise DhanHistoricalDataError("Dhan history returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise DhanHistoricalDataError("Dhan history returned non-object JSON")
        if parsed.get("status") == "failure" or parsed.get("errorCode"):
            raise DhanHistoricalDataError(f"Dhan history failure: {parsed}")
        return parsed


def normalize_dhan_intraday_response(
    payload: dict,
    *,
    instrument: CanonicalInstrument,
    interval_minutes: int,
    as_of: datetime,
) -> tuple[NormalizedCandle, ...]:
    _require_aware(as_of, "as_of")
    names = ("open", "high", "low", "close", "volume", "timestamp")
    arrays = {name: payload.get(name) for name in names}
    if any(not isinstance(value, list) for value in arrays.values()):
        raise DhanHistoricalDataError("Dhan history response missing OHLCV/timestamp arrays")
    lengths = {len(value) for value in arrays.values()}
    if len(lengths) != 1:
        raise DhanHistoricalDataError("Dhan history arrays have inconsistent lengths")

    duration = timedelta(minutes=interval_minutes)
    candles: list[NormalizedCandle] = []
    for index in range(next(iter(lengths), 0)):
        open_time = datetime.fromtimestamp(int(arrays["timestamp"][index]), tz=UTC)
        close_time = open_time + duration
        if close_time > as_of:
            continue
        candle = NormalizedCandle(
            symbol=instrument.canonical_symbol,
            venue="DHAN_LIVE",
            timeframe=f"{interval_minutes}m",
            open_time=open_time,
            close_time=close_time,
            open=_positive_decimal(arrays["open"][index], "open"),
            high=_positive_decimal(arrays["high"][index], "high"),
            low=_positive_decimal(arrays["low"][index], "low"),
            close=_positive_decimal(arrays["close"][index], "close"),
            volume=max(Decimal(0), _decimal(arrays["volume"][index])),
            closed=True,
        )
        candles.append(candle)
    candles.sort(key=lambda item: item.open_time)
    deduped: dict[datetime, NormalizedCandle] = {
        candle.open_time: candle for candle in candles
    }
    return tuple(deduped[key] for key in sorted(deduped))


def resample_india_session_candles(
    minute_candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle],
    timeframe: str,
) -> tuple[NormalizedCandle, ...]:
    """Aggregate complete 1m bars into India-session aligned higher timeframes.

    Missing one-minute bars make that higher-timeframe bucket ineligible instead
    of fabricating liquidity. The 09:15 Asia/Kolkata session anchor matches live
    Dhan candle aggregation, keeping warm-up and live paths structurally aligned.
    """

    if timeframe not in _RESAMPLE_MINUTES:
        raise ValueError(f"unsupported India resample timeframe: {timeframe}")
    minutes = _RESAMPLE_MINUTES[timeframe]
    ordered = sorted(minute_candles, key=lambda item: item.open_time)
    if timeframe == "1m":
        return tuple(item for item in ordered if item.closed and item.timeframe == "1m")
    if any(not item.closed or item.timeframe != "1m" for item in ordered):
        raise ValueError("India history resampling requires closed 1m candles")
    if not ordered:
        return ()

    buckets: dict[datetime, list[NormalizedCandle]] = defaultdict(list)
    duration = timedelta(minutes=minutes)
    for candle in ordered:
        local = candle.open_time.astimezone(_INDIA_TZ)
        anchor = datetime.combine(local.date(), time(9, 15), tzinfo=_INDIA_TZ)
        if local < anchor:
            continue
        elapsed_minutes = int((local - anchor).total_seconds() // 60)
        bucket_index = elapsed_minutes // minutes
        local_open = anchor + bucket_index * duration
        buckets[local_open.astimezone(UTC)].append(candle)

    result: list[NormalizedCandle] = []
    for open_time in sorted(buckets):
        bucket = sorted(buckets[open_time], key=lambda item: item.open_time)
        if len(bucket) != minutes:
            continue
        if any(
            right.open_time - left.open_time != timedelta(minutes=1)
            for left, right in pairwise(bucket)
        ):
            continue
        close_time = open_time + duration
        if bucket[-1].close_time != close_time:
            continue
        result.append(
            NormalizedCandle(
                symbol=bucket[0].symbol,
                venue=bucket[0].venue,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                open=bucket[0].open,
                high=max(item.high for item in bucket),
                low=min(item.low for item in bucket),
                close=bucket[-1].close,
                volume=sum((item.volume for item in bucket), Decimal(0)),
                closed=True,
            )
        )
    return tuple(result)


def _dhan_datetime(value: datetime) -> str:
    return value.astimezone(_INDIA_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _positive_decimal(value, name: str) -> Decimal:
    result = _decimal(value)
    if result <= 0:
        raise DhanHistoricalDataError(f"Dhan history {name} must be positive")
    return result


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DhanHistoricalDataError(f"invalid numeric Dhan history value: {value!r}") from exc
