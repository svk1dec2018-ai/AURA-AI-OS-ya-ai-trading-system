from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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


def _dhan_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


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
