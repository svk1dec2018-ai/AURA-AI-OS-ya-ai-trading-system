from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.data.dhan_live_ticker import DhanLiveCredentials
from aura.data.dhan_options import DhanOptionContract, parse_dhan_option_chain
from aura.markets.universe import AssetClass, CanonicalInstrument, OptionType
from aura.options.intelligence import (
    OptionChainAggregator,
    OptionContractObservation,
    OptionGreeks,
)

DHAN_OPTION_CHAIN_URL = "https://api.dhan.co/v2/optionchain"
_INDIA_TZ = ZoneInfo("Asia/Kolkata")


class DhanOptionChainError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class DhanOptionTarget:
    underlying_symbol: str
    security_id: str
    segment: str
    expiry: date

    @property
    def cache_key(self) -> str:
        return (
            f"{self.underlying_symbol.upper()}:{self.segment}:"
            f"{self.security_id}:{self.expiry.isoformat()}"
        )


class DhanOptionContextSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    underlying_symbol: str = Field(min_length=1)
    observed_at: datetime
    expiry: date
    implied_volatility: float | None = Field(default=None, ge=0.0)
    iv_percentile: float | None = Field(default=None, ge=0.0, le=100.0)
    put_call_oi_ratio: float | None = Field(default=None, ge=0.0)
    put_call_volume_ratio: float | None = Field(default=None, ge=0.0)
    expected_move_1sigma: Decimal | None = Field(default=None, ge=0)
    median_relative_spread_bps: float | None = Field(default=None, ge=0.0)
    liquid_contracts: int = Field(default=0, ge=0)
    contracts: int = Field(default=0, ge=0)
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Dhan option context timestamp must be timezone-aware")
        return value

    def as_agent_metadata(self) -> dict:
        return {
            "underlying_symbol": self.underlying_symbol,
            "options_snapshot": {
                "source_id": self.source_id,
                "underlying_symbol": self.underlying_symbol,
                "observed_at": self.observed_at.isoformat(),
                "implied_volatility": self.implied_volatility,
                "iv_percentile": self.iv_percentile,
                "put_call_oi_ratio": self.put_call_oi_ratio,
                "put_call_volume_ratio": self.put_call_volume_ratio,
                "trust_score": self.trust_score,
            },
            "option_chain": {
                "expiry": self.expiry.isoformat(),
                "expected_move_1sigma": (
                    str(self.expected_move_1sigma)
                    if self.expected_move_1sigma is not None
                    else None
                ),
                "median_relative_spread_bps": self.median_relative_spread_bps,
                "liquid_contracts": self.liquid_contracts,
                "contracts": self.contracts,
            },
        }


class DhanOptionTargetResolver:
    """Resolve a traded symbol to a point-in-time option-chain underlying.

    The resolver never invents a security id. It uses the canonical Dhan universe
    and returns no target when the underlying cannot be matched defensibly.
    """

    def __init__(self, instruments: tuple[CanonicalInstrument, ...] | list[CanonicalInstrument]) -> None:
        self._by_symbol = {item.canonical_symbol: item for item in instruments}
        self._options: dict[str, list[CanonicalInstrument]] = defaultdict(list)
        self._bases: dict[str, list[CanonicalInstrument]] = defaultdict(list)
        self._futures: dict[str, list[CanonicalInstrument]] = defaultdict(list)
        for instrument in instruments:
            if instrument.asset_class == AssetClass.OPTION and instrument.underlying:
                self._options[_symbol_key(instrument.underlying)].append(instrument)
            if instrument.asset_class in {
                AssetClass.INDEX,
                AssetClass.CASH_EQUITY,
                AssetClass.ETF,
            }:
                self._bases[_symbol_key(instrument.canonical_symbol)].append(instrument)
            if instrument.asset_class == AssetClass.FUTURE and instrument.underlying:
                self._futures[_symbol_key(instrument.underlying)].append(instrument)
        for collection in (*self._options.values(), *self._bases.values(), *self._futures.values()):
            collection.sort(key=_instrument_sort_key)

    def underlying_for(self, symbol: str) -> str | None:
        instrument = self._by_symbol.get(symbol)
        if instrument is None:
            return None
        return instrument.underlying or instrument.canonical_symbol

    def target_for(self, symbol: str, *, as_of: datetime) -> DhanOptionTarget | None:
        _require_aware(as_of, "as_of")
        instrument = self._by_symbol.get(symbol)
        if instrument is None:
            return None
        underlying = instrument.underlying or instrument.canonical_symbol
        key = _symbol_key(underlying)
        active_options = [
            item
            for item in self._options.get(key, ())
            if item.expiry is not None and item.expiry >= as_of
        ]
        if not active_options:
            return None
        expiry = min(item.expiry for item in active_options if item.expiry is not None)
        expiry_options = [item for item in active_options if item.expiry == expiry]
        option_exchange = expiry_options[0].exchange or ""

        base = self._select_base(key, option_exchange)
        if base is None:
            base = self._select_future(key, as_of, option_exchange)
        if base is None or not base.segment:
            return None
        return DhanOptionTarget(
            underlying_symbol=underlying,
            security_id=base.venue_symbol,
            segment=base.segment,
            expiry=expiry.date(),
        )

    def _select_base(self, key: str, option_exchange: str) -> CanonicalInstrument | None:
        candidates = list(self._bases.get(key, ()))
        if not candidates:
            return None

        def score(item: CanonicalInstrument) -> tuple[int, str, str]:
            if item.asset_class == AssetClass.INDEX:
                rank = 0
            elif option_exchange in {"NSE", "BSE"} and item.exchange == option_exchange:
                rank = 1
            elif item.exchange == "NSE":
                rank = 2
            else:
                rank = 3
            return rank, item.exchange or "", item.venue_symbol

        return min(candidates, key=score)

    def _select_future(
        self,
        key: str,
        as_of: datetime,
        option_exchange: str,
    ) -> CanonicalInstrument | None:
        candidates = [
            item
            for item in self._futures.get(key, ())
            if item.expiry is None or item.expiry >= as_of
        ]
        if option_exchange:
            aligned = [item for item in candidates if item.exchange == option_exchange]
            if aligned:
                candidates = aligned
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (
                item.expiry.isoformat() if item.expiry else "9999",
                item.venue_symbol,
            ),
        )


class DhanOptionChainClient:
    def __init__(
        self,
        credentials: DhanLiveCredentials,
        *,
        timeout_seconds: float = 15.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds

    def fetch_snapshot(
        self,
        target: DhanOptionTarget,
        *,
        observed_at: datetime | None = None,
    ) -> DhanOptionContextSnapshot:
        response = self._post(
            {
                "UnderlyingScrip": int(target.security_id),
                "UnderlyingSeg": target.segment,
                "Expiry": target.expiry.isoformat(),
            }
        )
        timestamp = observed_at or datetime.now(UTC)
        _require_aware(timestamp, "observed_at")
        return build_dhan_option_context_snapshot(
            response,
            target=target,
            observed_at=timestamp,
        )

    def _post(self, payload: dict) -> dict:
        request = Request(
            DHAN_OPTION_CHAIN_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "access-token": self.credentials.access_token,
                "client-id": self.credentials.client_id,
                "User-Agent": "AURA-AI-OS/0.1 option-context",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise DhanOptionChainError(
                f"Dhan option-chain HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise DhanOptionChainError(
                f"Dhan option-chain network error: {exc.reason}"
            ) from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise DhanOptionChainError("Dhan option-chain returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise DhanOptionChainError("Dhan option-chain returned non-object JSON")
        if parsed.get("status") == "failure" or parsed.get("errorCode"):
            raise DhanOptionChainError(f"Dhan option-chain failure: {parsed}")
        return parsed


class DhanOptionContextService:
    """Rate-aware live option context for the current deep shortlist.

    Dhan documents a three-second uniqueness interval for an option-chain request.
    AURA therefore rotates small batches of distinct underlyings and never polls
    one target faster than the configured interval.
    """

    def __init__(
        self,
        credentials: DhanLiveCredentials,
        resolver: DhanOptionTargetResolver,
        *,
        client: DhanOptionChainClient | None = None,
        request_interval_seconds: float = 3.2,
        max_requests_per_cycle: int = 4,
        max_staleness_seconds: float = 45.0,
    ) -> None:
        if request_interval_seconds < 3.0:
            raise ValueError("Dhan option-chain interval cannot be below 3 seconds")
        if max_requests_per_cycle <= 0 or max_requests_per_cycle > 5:
            raise ValueError("max_requests_per_cycle must be between 1 and 5")
        if max_staleness_seconds <= 0:
            raise ValueError("max_staleness_seconds must be positive")
        self.resolver = resolver
        self.client = client or DhanOptionChainClient(credentials)
        self.request_interval_seconds = request_interval_seconds
        self.max_requests_per_cycle = max_requests_per_cycle
        self.max_staleness = timedelta(seconds=max_staleness_seconds)
        self._symbols: tuple[str, ...] = ()
        self._cache: dict[str, DhanOptionContextSnapshot] = {}
        self._last_request_at: dict[str, datetime] = {}
        self._worker: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._cursor = 0
        self.last_errors: dict[str, str] = {}

    @property
    def active_symbols(self) -> tuple[str, ...]:
        return self._symbols

    async def update_symbols(self, symbols: tuple[str, ...] | list[str]) -> bool:
        requested = tuple(sorted(set(symbols)))
        changed = requested != self._symbols
        self._symbols = requested
        if requested and (self._worker is None or self._worker.done()):
            self._stop.clear()
            self._worker = asyncio.create_task(self._run())
        return changed

    def metadata_for(self, symbol: str, *, decision_time: datetime) -> dict:
        _require_aware(decision_time, "decision_time")
        underlying = self.resolver.underlying_for(symbol)
        if not underlying:
            return {}
        metadata: dict = {"underlying_symbol": underlying}
        target = self.resolver.target_for(symbol, as_of=decision_time)
        if target is None:
            return metadata
        snapshot = self._cache.get(target.cache_key)
        if snapshot is None:
            return metadata
        if snapshot.observed_at > decision_time:
            return metadata
        if decision_time - snapshot.observed_at > self.max_staleness:
            return metadata
        metadata.update(snapshot.as_agent_metadata())
        return metadata

    async def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None

    def status(self) -> dict:
        return {
            "active_symbols": len(self._symbols),
            "cached_chains": len(self._cache),
            "errors": dict(sorted(self.last_errors.items())[:20]),
        }

    async def _run(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(UTC)
            targets = self._targets(now)
            eligible = [
                target
                for target in targets
                if target.cache_key not in self._last_request_at
                or now - self._last_request_at[target.cache_key]
                >= timedelta(seconds=self.request_interval_seconds)
            ]
            if eligible:
                start = self._cursor % len(eligible)
                rotated = eligible[start:] + eligible[:start]
                batch = rotated[: self.max_requests_per_cycle]
                self._cursor = (start + len(batch)) % max(len(eligible), 1)
                results = await asyncio.gather(
                    *(
                        asyncio.to_thread(self.client.fetch_snapshot, target)
                        for target in batch
                    ),
                    return_exceptions=True,
                )
                request_time = datetime.now(UTC)
                for target, result in zip(batch, results, strict=True):
                    self._last_request_at[target.cache_key] = request_time
                    if isinstance(result, Exception):
                        self.last_errors[target.cache_key] = (
                            f"{type(result).__name__}: {result}"
                        )
                        continue
                    self._cache[target.cache_key] = result
                    self.last_errors.pop(target.cache_key, None)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.request_interval_seconds,
                )
            except TimeoutError:
                continue

    def _targets(self, as_of: datetime) -> list[DhanOptionTarget]:
        unique: dict[str, DhanOptionTarget] = {}
        for symbol in self._symbols:
            target = self.resolver.target_for(symbol, as_of=as_of)
            if target is not None:
                unique[target.cache_key] = target
        return [unique[key] for key in sorted(unique)]


def build_dhan_option_context_snapshot(
    response: dict,
    *,
    target: DhanOptionTarget,
    observed_at: datetime,
) -> DhanOptionContextSnapshot:
    _require_aware(observed_at, "observed_at")
    contracts = parse_dhan_option_chain(
        response,
        underlying=target.underlying_symbol,
        expiry=target.expiry.isoformat(),
    )
    if not contracts:
        raise DhanOptionChainError("Dhan option-chain contained no contracts")
    try:
        spot = _positive_decimal(response["data"]["last_price"], "last_price")
    except (KeyError, TypeError) as exc:
        raise DhanOptionChainError("Dhan option-chain missing data.last_price") from exc
    expiry_at = _expiry_datetime(target)
    observations = tuple(
        _to_observation(
            contract,
            spot=spot,
            expiry_at=expiry_at,
            observed_at=observed_at,
        )
        for contract in contracts
    )
    intelligence = OptionChainAggregator().aggregate(
        observations,
        as_of=observed_at,
    )
    return DhanOptionContextSnapshot(
        source_id=(
            f"dhan-option-chain:{target.segment}:{target.security_id}:"
            f"{target.expiry.isoformat()}"
        ),
        underlying_symbol=target.underlying_symbol,
        observed_at=observed_at,
        expiry=target.expiry,
        implied_volatility=intelligence.atm_iv,
        iv_percentile=None,
        put_call_oi_ratio=intelligence.put_call_oi_ratio,
        put_call_volume_ratio=intelligence.put_call_volume_ratio,
        expected_move_1sigma=intelligence.expected_move_1sigma,
        median_relative_spread_bps=intelligence.median_relative_spread_bps,
        liquid_contracts=intelligence.liquid_contracts,
        contracts=intelligence.contracts,
    )


def _to_observation(
    contract: DhanOptionContract,
    *,
    spot: Decimal,
    expiry_at: datetime,
    observed_at: datetime,
) -> OptionContractObservation:
    return OptionContractObservation(
        underlying=contract.underlying,
        expiry=expiry_at,
        strike=contract.strike,
        option_type=(
            OptionType.CALL if contract.option_type == "CE" else OptionType.PUT
        ),
        spot=spot,
        last_price=Decimal(str(contract.last_price)),
        bid=Decimal(str(contract.top_bid_price)),
        ask=Decimal(str(contract.top_ask_price)),
        open_interest=Decimal(contract.open_interest),
        volume=Decimal(contract.volume),
        implied_volatility=contract.implied_volatility,
        greeks=OptionGreeks(
            delta=contract.greeks.delta,
            gamma=contract.greeks.gamma,
            theta=contract.greeks.theta,
            vega=contract.greeks.vega,
        ),
        observed_at=observed_at,
    )


def _expiry_datetime(target: DhanOptionTarget) -> datetime:
    close = time(23, 30) if target.segment == "MCX_COMM" else time(15, 30)
    return datetime.combine(target.expiry, close, tzinfo=_INDIA_TZ).astimezone(UTC)


def _symbol_key(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _instrument_sort_key(item: CanonicalInstrument) -> tuple[str, str, str]:
    return (
        item.expiry.isoformat() if item.expiry else "",
        item.exchange or "",
        item.venue_symbol,
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _positive_decimal(value, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DhanOptionChainError(f"invalid Dhan option-chain {name}: {value!r}") from exc
    if result <= 0:
        raise DhanOptionChainError(f"Dhan option-chain {name} must be positive")
    return result
