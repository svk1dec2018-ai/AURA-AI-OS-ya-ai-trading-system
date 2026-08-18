from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from aura.data.cross_feed import QuoteObservation
from aura.domain.models import NormalizedCandle

_OANDA_REST = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}
_GRANULARITY_TO_TIMEFRAME = {
    "M1": ("1m", timedelta(minutes=1)),
    "M5": ("5m", timedelta(minutes=5)),
    "M15": ("15m", timedelta(minutes=15)),
    "M30": ("30m", timedelta(minutes=30)),
    "H1": ("1h", timedelta(hours=1)),
    "H4": ("4h", timedelta(hours=4)),
    "D": ("1d", timedelta(days=1)),
}


class OandaError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class OandaCredentials:
    account_id: str
    access_token: str
    environment: str = "practice"

    def __post_init__(self) -> None:
        if not self.account_id or not self.access_token:
            raise ValueError("OANDA account_id/access_token are required")
        if self.environment not in _OANDA_REST:
            raise ValueError("OANDA environment must be practice or live")


def load_oanda_credentials_from_env() -> OandaCredentials:
    account_id = os.environ.get("AURA_OANDA_ACCOUNT_ID", "").strip()
    token = os.environ.get("AURA_OANDA_ACCESS_TOKEN", "").strip()
    environment = os.environ.get("AURA_OANDA_ENVIRONMENT", "practice").strip().lower()
    if not account_id or not token:
        raise RuntimeError("set AURA_OANDA_ACCOUNT_ID and AURA_OANDA_ACCESS_TOKEN")
    return OandaCredentials(
        account_id=account_id,
        access_token=token,
        environment=environment,
    )


class OandaMarketDataClient:
    """Read-only v20 pricing/candle client; defaults to the practice environment."""

    def __init__(
        self,
        credentials: OandaCredentials,
        *,
        timeout_seconds: float = 15.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds
        self.base_url = _OANDA_REST[credentials.environment]

    def pricing(
        self,
        instruments: tuple[str, ...] | list[str],
        *,
        observed_at: datetime | None = None,
    ) -> tuple[QuoteObservation, ...]:
        requested = tuple(sorted({item.strip().upper() for item in instruments if item.strip()}))
        if not requested:
            raise ValueError("OANDA pricing requires instruments")
        received_at = observed_at or datetime.now(UTC)
        _require_aware(received_at, "observed_at")
        payload = self._get(
            f"/v3/accounts/{self.credentials.account_id}/pricing",
            {"instruments": ",".join(requested)},
        )
        prices = payload.get("prices", []) if isinstance(payload, dict) else []
        result: list[QuoteObservation] = []
        for item in prices:
            if not isinstance(item, dict) or item.get("status") not in {None, "tradeable"}:
                continue
            instrument = str(item.get("instrument") or "").strip().upper()
            bids = item.get("bids", [])
            asks = item.get("asks", [])
            if not instrument or not bids or not asks:
                continue
            bid = _positive_decimal(bids[0].get("price"), "bid")
            ask = _positive_decimal(asks[0].get("price"), "ask")
            if ask < bid:
                continue
            observed = _parse_oanda_time(item.get("time"), fallback=received_at)
            if observed > received_at:
                continue
            result.append(
                QuoteObservation(
                    provider=f"OANDA_{self.credentials.environment.upper()}",
                    symbol=instrument,
                    last=(bid + ask) / Decimal(2),
                    bid=bid,
                    ask=ask,
                    observed_at=observed,
                    received_at=received_at,
                    trust_score=1.0,
                )
            )
        return tuple(sorted(result, key=lambda item: item.symbol))

    def candles(
        self,
        instrument: str,
        *,
        granularity: str = "M1",
        count: int = 500,
        as_of: datetime | None = None,
    ) -> tuple[NormalizedCandle, ...]:
        granularity = granularity.upper()
        if granularity not in _GRANULARITY_TO_TIMEFRAME:
            raise ValueError("unsupported AURA OANDA granularity")
        if not 1 <= count <= 5000:
            raise ValueError("OANDA candle count must be between 1 and 5000")
        decision_time = as_of or datetime.now(UTC)
        _require_aware(decision_time, "as_of")
        symbol = instrument.strip().upper()
        if not symbol:
            raise ValueError("OANDA instrument cannot be empty")
        payload = self._get(
            f"/v3/accounts/{self.credentials.account_id}/instruments/{symbol}/candles",
            {
                "granularity": granularity,
                "price": "M",
                "count": str(count),
            },
        )
        timeframe, duration = _GRANULARITY_TO_TIMEFRAME[granularity]
        rows = payload.get("candles", []) if isinstance(payload, dict) else []
        candles: list[NormalizedCandle] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("complete"):
                continue
            mid = row.get("mid")
            if not isinstance(mid, dict):
                continue
            open_time = _parse_oanda_time(row.get("time"), fallback=decision_time)
            close_time = open_time + duration
            if close_time > decision_time:
                continue
            candles.append(
                NormalizedCandle(
                    symbol=symbol,
                    venue=f"OANDA_{self.credentials.environment.upper()}",
                    timeframe=timeframe,
                    open_time=open_time,
                    close_time=close_time,
                    open=_positive_decimal(mid.get("o"), "open"),
                    high=_positive_decimal(mid.get("h"), "high"),
                    low=_positive_decimal(mid.get("l"), "low"),
                    close=_positive_decimal(mid.get("c"), "close"),
                    volume=Decimal(str(max(int(row.get("volume", 0)), 0))),
                    closed=True,
                )
            )
        unique = {item.open_time: item for item in candles}
        return tuple(unique[key] for key in sorted(unique))

    def _get(self, path: str, params: dict[str, str]) -> dict:
        url = f"{self.base_url}{path}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self.credentials.access_token}",
                "Accept": "application/json",
                "User-Agent": "AURA-AI-OS/0.1 oanda-data",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode()
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise OandaError(f"OANDA HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise OandaError(f"OANDA network error: {exc.reason}") from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OandaError("OANDA returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise OandaError("OANDA returned non-object JSON")
        if parsed.get("errorMessage"):
            raise OandaError(str(parsed["errorMessage"]))
        return parsed


def _parse_oanda_time(value, *, fallback: datetime) -> datetime:
    text = str(value or "").strip()
    if not text:
        return fallback.astimezone(UTC)
    normalized = text
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    match = re.match(r"^(.*\.)(\d{7,})([+-]\d\d:\d\d)$", normalized)
    if match:
        normalized = f"{match.group(1)}{match.group(2)[:6]}{match.group(3)}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise OandaError(f"invalid OANDA timestamp: {text!r}") from exc
    if parsed.tzinfo is None:
        raise OandaError("OANDA timestamp is timezone-naive")
    return parsed.astimezone(UTC)


def _positive_decimal(value, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OandaError(f"invalid OANDA {name}: {value!r}") from exc
    if result <= 0:
        raise OandaError(f"OANDA {name} must be positive")
    return result


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
