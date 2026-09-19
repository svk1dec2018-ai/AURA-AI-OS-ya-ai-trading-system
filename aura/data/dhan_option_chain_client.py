from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aura.data.dhan_live_ticker import DhanLiveCredentials
from aura.markets.universe import OptionType
from aura.options.intelligence import OptionContractObservation, OptionGreeks

DHAN_API_BASE = "https://api.dhan.co/v2"
DHAN_OPTION_CHAIN_URL = f"{DHAN_API_BASE}/optionchain"
DHAN_EXPIRY_LIST_URL = f"{DHAN_API_BASE}/optionchain/expirylist"


class DhanOptionChainError(RuntimeError):
    pass


class DhanOptionChainClient:
    """Rate-limited Dhan v2 option-chain client with point-in-time normalization."""

    def __init__(
        self,
        credentials: DhanLiveCredentials,
        *,
        minimum_request_interval_seconds: float = 3.0,
        timeout_seconds: float = 20.0,
    ) -> None:
        if minimum_request_interval_seconds < 3.0:
            raise ValueError("Dhan option-chain requests must be spaced by at least 3s")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.credentials = credentials
        self.minimum_request_interval_seconds = minimum_request_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._last_request_monotonic = 0.0

    def expiry_list(
        self,
        *,
        underlying_security_id: int,
        underlying_segment: str,
    ) -> tuple[str, ...]:
        payload = self._post(
            DHAN_EXPIRY_LIST_URL,
            {
                "UnderlyingScrip": underlying_security_id,
                "UnderlyingSeg": underlying_segment,
            },
        )
        data = payload.get("data", payload)
        if not isinstance(data, list):
            raise DhanOptionChainError("Dhan expiry-list response has unexpected shape")
        return tuple(str(item) for item in data if str(item).strip())

    def observations(
        self,
        *,
        underlying: str,
        underlying_security_id: int,
        underlying_segment: str,
        expiry: str,
        observed_at: datetime | None = None,
    ) -> tuple[OptionContractObservation, ...]:
        timestamp = observed_at or datetime.now(UTC)
        payload = self._post(
            DHAN_OPTION_CHAIN_URL,
            {
                "UnderlyingScrip": underlying_security_id,
                "UnderlyingSeg": underlying_segment,
                "Expiry": expiry,
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise DhanOptionChainError("Dhan option-chain response has no data object")
        spot = _decimal(data.get("last_price"), default=Decimal(0))
        chain = data.get("oc")
        if spot <= 0 or not isinstance(chain, dict):
            raise DhanOptionChainError("Dhan option-chain response missing spot/chain")
        expiry_dt = _expiry_datetime(expiry)
        observations: list[OptionContractObservation] = []
        for strike_text, strike_payload in chain.items():
            if not isinstance(strike_payload, dict):
                continue
            strike = _decimal(strike_text, default=Decimal(0))
            if strike <= 0:
                continue
            for key, option_type in (("ce", OptionType.CALL), ("pe", OptionType.PUT)):
                raw = strike_payload.get(key)
                if not isinstance(raw, dict):
                    continue
                greeks_raw = raw.get("greeks")
                greeks_raw = greeks_raw if isinstance(greeks_raw, dict) else {}
                bid = _decimal(
                    raw.get("top_bid_price", _nested(raw, "market_depth", "bid")),
                    default=Decimal(0),
                )
                ask = _decimal(
                    raw.get("top_ask_price", _nested(raw, "market_depth", "ask")),
                    default=Decimal(0),
                )
                observations.append(
                    OptionContractObservation(
                        underlying=underlying,
                        expiry=expiry_dt,
                        strike=strike,
                        option_type=option_type,
                        spot=spot,
                        last_price=_decimal(raw.get("last_price"), default=Decimal(0)),
                        bid=max(Decimal(0), bid),
                        ask=max(Decimal(0), ask),
                        open_interest=max(
                            Decimal(0),
                            _decimal(raw.get("oi"), default=Decimal(0)),
                        ),
                        volume=max(
                            Decimal(0),
                            _decimal(raw.get("volume"), default=Decimal(0)),
                        ),
                        implied_volatility=max(
                            0.0,
                            _float(raw.get("implied_volatility"), default=0.0),
                        ),
                        greeks=OptionGreeks(
                            delta=_float(greeks_raw.get("delta"), default=0.0),
                            gamma=_float(greeks_raw.get("gamma"), default=0.0),
                            theta=_float(greeks_raw.get("theta"), default=0.0),
                            vega=_float(greeks_raw.get("vega"), default=0.0),
                        ),
                        observed_at=timestamp,
                    )
                )
        return tuple(observations)

    def _post(self, url: str, body: dict) -> dict:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_monotonic
            sleep_for = self.minimum_request_interval_seconds - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            request = Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "access-token": self.credentials.access_token,
                    "client-id": self.credentials.client_id,
                    "User-Agent": "AURA-AI-OS/0.1 option-chain",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                raise DhanOptionChainError(
                    f"Dhan option-chain HTTP {exc.code}: {detail}"
                ) from exc
            except URLError as exc:
                raise DhanOptionChainError(
                    f"Dhan option-chain network error: {exc.reason}"
                ) from exc
            finally:
                self._last_request_monotonic = time.monotonic()
        if not isinstance(payload, dict):
            raise DhanOptionChainError("Dhan option-chain returned non-object JSON")
        if payload.get("status") == "failure":
            raise DhanOptionChainError(f"Dhan option-chain failure: {payload}")
        return payload


def _decimal(value, *, default: Decimal) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return default


def _float(value, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nested(payload: dict, outer: str, inner: str):
    value = payload.get(outer)
    return value.get(inner) if isinstance(value, dict) else None


def _expiry_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(hour=10, tzinfo=UTC)
        except ValueError:
            continue
    raise DhanOptionChainError(f"unsupported Dhan expiry date: {value}")
