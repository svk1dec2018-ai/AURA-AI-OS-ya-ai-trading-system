from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.domain.models import NormalizedCandle


class FuturesContractMetadata(BaseModel):
    """Immutable contract identity and provenance for historical futures research."""

    model_config = ConfigDict(frozen=True)

    contract_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    underlying: str = Field(min_length=1)
    venue: str = Field(min_length=1)
    expiry_at: datetime
    observed_at: datetime
    source: str = Field(min_length=1)
    source_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("contract_id", "symbol", "underlying", "venue", "source")
    @classmethod
    def normalize_text(cls, value: str, info) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("futures contract text fields must not be blank")
        if info.field_name in {"symbol", "underlying", "venue"}:
            return normalized.upper()
        return normalized

    @field_validator("expiry_at", "observed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("futures contract timestamps must be timezone-aware")
        return value


class FuturesRollEvent(BaseModel):
    """A precommitted transition between two actual listed contracts."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    from_contract_id: str = Field(min_length=1)
    to_contract_id: str = Field(min_length=1)
    roll_at: datetime
    observed_at: datetime
    rule_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("event_id", "from_contract_id", "to_contract_id", "rule_id", "source")
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("futures roll text fields must not be blank")
        return normalized

    @field_validator("roll_at", "observed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("futures roll timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_precommitment(self) -> FuturesRollEvent:
        if self.from_contract_id == self.to_contract_id:
            raise ValueError("futures roll must change contract")
        if self.observed_at > self.roll_at:
            raise ValueError("futures roll rule must be observed no later than roll_at")
        return self


class RolledResearchCandle(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence: int = Field(ge=0)
    contract_id: str
    return_reset: bool
    candle: NormalizedCandle


class FuturesRollBoundary(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    from_contract_id: str
    to_contract_id: str
    roll_at: datetime
    from_last_close: Decimal = Field(gt=0)
    to_first_open: Decimal = Field(gt=0)
    raw_price_gap: Decimal
    raw_price_ratio: Decimal = Field(gt=0)
    return_reset: bool = True
    rule_id: str
    source: str
    source_artifact_hash: str


class FuturesRolledSeries(BaseModel):
    """Actual-contract candle sequence with explicit non-return roll boundaries."""

    model_config = ConfigDict(frozen=True)

    underlying: str
    venue: str
    timeframe: str
    as_of: datetime
    active_contract_id: str
    price_adjustment_applied: bool = False
    candles: tuple[RolledResearchCandle, ...]
    boundaries: tuple[FuturesRollBoundary, ...]
    deferred_roll_ids: tuple[str, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def stitch_futures_contracts(
    contracts: list[FuturesContractMetadata] | tuple[FuturesContractMetadata, ...],
    rolls: list[FuturesRollEvent] | tuple[FuturesRollEvent, ...],
    contract_series: dict[str, list[NormalizedCandle] | tuple[NormalizedCandle, ...]],
    *,
    as_of: datetime,
) -> FuturesRolledSeries:
    """Stitch actual contracts without manufacturing or back-adjusting market prices."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("futures roll as_of must be timezone-aware")
    ordered_contracts = _validate_contracts(tuple(contracts))
    ordered_rolls = _validate_rolls(ordered_contracts, tuple(rolls))
    active_rolls = tuple(event for event in ordered_rolls if event.roll_at <= as_of)
    deferred_rolls = tuple(event for event in ordered_rolls if event.roll_at > as_of)
    _validate_active_chain(ordered_contracts, active_rolls)

    current_index = len(active_rolls)
    if current_index >= len(ordered_contracts):
        raise ValueError("futures roll chain exceeds declared contracts")
    current = ordered_contracts[current_index]
    if as_of > current.expiry_at:
        raise ValueError(f"no eligible roll before contract expiry: {current.contract_id}")

    required_contracts = ordered_contracts[: current_index + 1]
    if any(contract.observed_at > as_of for contract in required_contracts):
        raise ValueError("active futures contract metadata is not yet observed at as_of")
    required_ids = {contract.contract_id for contract in required_contracts}
    if set(contract_series) != required_ids:
        raise ValueError("contract_series must contain exactly the point-in-time active chain")

    series_by_id: dict[str, tuple[NormalizedCandle, ...]] = {}
    timeframe: str | None = None
    for contract in required_contracts:
        series = tuple(contract_series[contract.contract_id])
        _validate_contract_series(contract, series, as_of=as_of)
        if timeframe is None:
            timeframe = series[0].timeframe
        elif series[0].timeframe != timeframe:
            raise ValueError("all rolled futures series must use one timeframe")
        series_by_id[contract.contract_id] = series

    selected_by_id: dict[str, tuple[NormalizedCandle, ...]] = {}
    for index, contract in enumerate(required_contracts):
        lower = active_rolls[index - 1].roll_at if index > 0 else None
        upper = active_rolls[index].roll_at if index < len(active_rolls) else None
        series = series_by_id[contract.contract_id]
        for candle in series:
            if lower is not None and candle.open_time < lower < candle.close_time:
                raise ValueError(
                    f"candle crosses incoming roll boundary for {contract.contract_id}"
                )
            if upper is not None and candle.open_time < upper < candle.close_time:
                raise ValueError(
                    f"candle crosses outgoing roll boundary for {contract.contract_id}"
                )
        selected = tuple(
            candle
            for candle in series
            if (lower is None or candle.open_time >= lower)
            and (upper is None or candle.close_time <= upper)
        )
        if not selected:
            raise ValueError(f"no eligible candles for rolled contract {contract.contract_id}")
        selected_by_id[contract.contract_id] = selected

    boundaries = tuple(
        _build_boundary(
            event,
            selected_by_id[event.from_contract_id][-1],
            selected_by_id[event.to_contract_id][0],
        )
        for event in active_rolls
    )
    stitched: list[RolledResearchCandle] = []
    sequence = 0
    for contract in required_contracts:
        for index, candle in enumerate(selected_by_id[contract.contract_id]):
            stitched.append(
                RolledResearchCandle(
                    sequence=sequence,
                    contract_id=contract.contract_id,
                    return_reset=sequence == 0 or index == 0,
                    candle=candle,
                )
            )
            sequence += 1

    payload = {
        "as_of": as_of.isoformat(),
        "contracts": [contract.model_dump(mode="json") for contract in required_contracts],
        "rolls": [event.model_dump(mode="json") for event in active_rolls],
        "candles": [item.model_dump(mode="json") for item in stitched],
    }
    return FuturesRolledSeries(
        underlying=current.underlying,
        venue=current.venue,
        timeframe=timeframe or "",
        as_of=as_of,
        active_contract_id=current.contract_id,
        candles=tuple(stitched),
        boundaries=boundaries,
        deferred_roll_ids=tuple(event.event_id for event in deferred_rolls),
        content_hash=_canonical_hash(payload),
    )


def _validate_contracts(
    contracts: tuple[FuturesContractMetadata, ...],
) -> tuple[FuturesContractMetadata, ...]:
    if not contracts:
        raise ValueError("futures roll requires at least one contract")
    if len({item.contract_id for item in contracts}) != len(contracts):
        raise ValueError("futures contract IDs must be unique")
    if len({item.symbol for item in contracts}) != len(contracts):
        raise ValueError("futures contract symbols must be unique")
    if len({(item.underlying, item.venue) for item in contracts}) != 1:
        raise ValueError("futures contracts must share one underlying and venue")
    ordered = tuple(sorted(contracts, key=lambda item: (item.expiry_at, item.contract_id)))
    if any(current.expiry_at >= following.expiry_at for current, following in pairwise(ordered)):
        raise ValueError("futures contract expiries must be strictly increasing")
    return ordered


def _validate_rolls(
    contracts: tuple[FuturesContractMetadata, ...],
    rolls: tuple[FuturesRollEvent, ...],
) -> tuple[FuturesRollEvent, ...]:
    if len({event.event_id for event in rolls}) != len(rolls):
        raise ValueError("futures roll event IDs must be unique")
    by_id = {contract.contract_id: contract for contract in contracts}
    index_by_id = {contract.contract_id: index for index, contract in enumerate(contracts)}
    ordered = tuple(sorted(rolls, key=lambda event: (event.roll_at, event.event_id)))
    for event in ordered:
        if event.from_contract_id not in by_id or event.to_contract_id not in by_id:
            raise ValueError(f"futures roll references unknown contract: {event.event_id}")
        from_index = index_by_id[event.from_contract_id]
        if (
            from_index + 1 >= len(contracts)
            or contracts[from_index + 1].contract_id != event.to_contract_id
        ):
            raise ValueError("futures roll must transition to the next declared expiry")
        if event.roll_at >= by_id[event.from_contract_id].expiry_at:
            raise ValueError("futures roll must occur before outgoing contract expiry")
        if event.roll_at >= by_id[event.to_contract_id].expiry_at:
            raise ValueError("futures roll must occur before incoming contract expiry")
    for index, event in enumerate(ordered):
        if (
            index + 1 >= len(contracts)
            or event.from_contract_id != contracts[index].contract_id
            or event.to_contract_id != contracts[index + 1].contract_id
        ):
            raise ValueError("declared futures rolls must form a contiguous expiry chain")
    if any(current.roll_at >= following.roll_at for current, following in pairwise(ordered)):
        raise ValueError("futures roll times must be strictly increasing")
    return ordered


def _validate_active_chain(
    contracts: tuple[FuturesContractMetadata, ...],
    rolls: tuple[FuturesRollEvent, ...],
) -> None:
    for index, event in enumerate(rolls):
        if index + 1 >= len(contracts):
            raise ValueError("futures active roll chain exceeds declared contracts")
        if (
            event.from_contract_id != contracts[index].contract_id
            or event.to_contract_id != contracts[index + 1].contract_id
        ):
            raise ValueError("futures active rolls must form a contiguous chain")


def _validate_contract_series(
    contract: FuturesContractMetadata,
    candles: tuple[NormalizedCandle, ...],
    *,
    as_of: datetime,
) -> None:
    if not candles:
        raise ValueError(f"missing candle evidence for contract {contract.contract_id}")
    previous: NormalizedCandle | None = None
    for candle in candles:
        if not candle.closed:
            raise ValueError("futures roll accepts only closed candles")
        if (
            candle.symbol.strip().upper() != contract.symbol
            or candle.venue.strip().upper() != contract.venue
        ):
            raise ValueError(f"candle identity does not match contract {contract.contract_id}")
        if candle.close_time > as_of:
            raise ValueError("futures candle closes after roll as_of")
        if candle.close_time > contract.expiry_at:
            raise ValueError(f"candle closes after contract expiry: {contract.contract_id}")
        if previous is not None:
            if candle.open_time <= previous.open_time:
                raise ValueError("futures candles must be strictly chronological")
            if candle.open_time < previous.close_time:
                raise ValueError("futures candles must not overlap")
            if candle.timeframe != previous.timeframe:
                raise ValueError("one contract series must use one timeframe")
        previous = candle


def _build_boundary(
    event: FuturesRollEvent,
    outgoing: NormalizedCandle,
    incoming: NormalizedCandle,
) -> FuturesRollBoundary:
    if outgoing.close_time > event.roll_at or incoming.open_time < event.roll_at:
        raise ValueError(f"roll boundary candles are not separated at {event.event_id}")
    return FuturesRollBoundary(
        event_id=event.event_id,
        from_contract_id=event.from_contract_id,
        to_contract_id=event.to_contract_id,
        roll_at=event.roll_at,
        from_last_close=outgoing.close,
        to_first_open=incoming.open,
        raw_price_gap=incoming.open - outgoing.close,
        raw_price_ratio=incoming.open / outgoing.close,
        rule_id=event.rule_id,
        source=event.source,
        source_artifact_hash=event.source_artifact_hash,
    )


def _canonical_hash(payload: object) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
