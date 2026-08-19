from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.markets.universe import OptionType
from aura.options.intelligence import OptionContractObservation


def _require_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


class OptionChainSnapshot(BaseModel):
    """One atomic, source-addressed historical option-chain observation."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    underlying: str = Field(min_length=1)
    expiry: datetime
    observed_at: datetime
    contracts: tuple[OptionContractObservation, ...] = Field(min_length=1)

    @field_validator("snapshot_id", "source")
    @classmethod
    def _strip_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("underlying")
    @classmethod
    def _normalize_underlying(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("underlying cannot be blank")
        return value

    @model_validator(mode="after")
    def _validate_atomic_snapshot(self) -> OptionChainSnapshot:
        _require_aware(self.expiry, field="expiry")
        _require_aware(self.observed_at, field="observed_at")
        if self.expiry <= self.observed_at:
            raise ValueError("snapshot must be observed before expiry")

        keys: set[tuple[Decimal, OptionType]] = set()
        spots: set[Decimal] = set()
        for contract in self.contracts:
            _require_aware(contract.expiry, field="contract expiry")
            _require_aware(contract.observed_at, field="contract observed_at")
            if contract.underlying.strip().upper() != self.underlying:
                raise ValueError("contract underlying does not match snapshot")
            if contract.expiry != self.expiry:
                raise ValueError("contract expiry does not match snapshot")
            if contract.observed_at != self.observed_at:
                raise ValueError("contracts must share the atomic snapshot timestamp")
            key = (contract.strike, contract.option_type)
            if key in keys:
                raise ValueError("duplicate strike/option_type contract in snapshot")
            keys.add(key)
            spots.add(contract.spot)
            if (contract.bid > 0) != (contract.ask > 0):
                raise ValueError("contract quote must be two-sided or absent")
            if contract.bid > 0 and contract.ask < contract.bid:
                raise ValueError("contract ask cannot be below bid")
            metrics = (
                contract.implied_volatility,
                contract.greeks.delta,
                contract.greeks.gamma,
                contract.greeks.theta,
                contract.greeks.vega,
            )
            if not all(math.isfinite(metric) for metric in metrics):
                raise ValueError("option metrics must be finite")
        if len(spots) != 1:
            raise ValueError("all contracts in an atomic snapshot must share spot")
        return self


@dataclass(slots=True, frozen=True)
class OptionChainReplayPolicy:
    max_staleness: timedelta = timedelta(minutes=5)
    min_contracts: int = 2
    min_paired_strikes: int = 1
    min_quoted_contract_fraction: float = 0.5
    require_call_and_put: bool = True

    def __post_init__(self) -> None:
        if self.max_staleness <= timedelta(0):
            raise ValueError("max_staleness must be positive")
        if self.min_contracts < 1:
            raise ValueError("min_contracts must be positive")
        if self.min_paired_strikes < 0:
            raise ValueError("min_paired_strikes cannot be negative")
        if not 0 <= self.min_quoted_contract_fraction <= 1:
            raise ValueError("min_quoted_contract_fraction must be in [0, 1]")


class OptionChainReplayFrame(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_at: datetime
    snapshot_id: str
    source: str
    source_artifact_hash: str
    observed_at: datetime
    age_seconds: float = Field(ge=0)
    contracts: tuple[OptionContractObservation, ...]
    call_count: int = Field(ge=0)
    put_count: int = Field(ge=0)
    paired_strikes: int = Field(ge=0)
    quoted_contract_fraction: float = Field(ge=0, le=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class OptionChainReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    underlying: str
    expiry: datetime
    frames: tuple[OptionChainReplayFrame, ...]
    replay_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def replay_option_chain(
    snapshots: tuple[OptionChainSnapshot, ...] | list[OptionChainSnapshot],
    decision_times: tuple[datetime, ...] | list[datetime],
    *,
    policy: OptionChainReplayPolicy | None = None,
) -> OptionChainReplayResult:
    """Replay exact recorded chains at decision times without interpolation or look-ahead."""

    if not snapshots:
        raise ValueError("option-chain snapshots cannot be empty")
    if not decision_times:
        raise ValueError("decision_times cannot be empty")
    policy = policy or OptionChainReplayPolicy()
    # Reconstruct at the trust boundary so model_copy/model_construct cannot
    # smuggle an unvalidated archive record into a research replay.
    snapshots = tuple(
        OptionChainSnapshot.model_validate(snapshot.model_dump()) for snapshot in snapshots
    )
    decisions = tuple(decision_times)
    for decision in decisions:
        _require_aware(decision, field="decision time")
    if any(current <= previous for previous, current in pairwise(decisions)):
        raise ValueError("decision_times must be strictly increasing")

    first = snapshots[0]
    if any(
        snapshot.underlying != first.underlying or snapshot.expiry != first.expiry
        for snapshot in snapshots
    ):
        raise ValueError("replay one underlying/expiry at a time")
    ids = [snapshot.snapshot_id for snapshot in snapshots]
    if len(ids) != len(set(ids)):
        raise ValueError("snapshot_id values must be unique")
    observed_times = [snapshot.observed_at for snapshot in snapshots]
    if len(observed_times) != len(set(observed_times)):
        raise ValueError("snapshot timestamps must be unique")
    if any(decision >= first.expiry for decision in decisions):
        raise ValueError("decision times must be before option expiry")

    # Excluding observations after the final decision also keeps replay identity
    # invariant when a future archive partition is appended.
    eligible = sorted(
        (snapshot for snapshot in snapshots if snapshot.observed_at <= decisions[-1]),
        key=lambda snapshot: snapshot.observed_at,
    )
    frames: list[OptionChainReplayFrame] = []
    for decision in decisions:
        visible = [snapshot for snapshot in eligible if snapshot.observed_at <= decision]
        if not visible:
            raise ValueError(f"no visible option-chain snapshot at {decision.isoformat()}")
        snapshot = visible[-1]
        age = decision - snapshot.observed_at
        if age > policy.max_staleness:
            raise ValueError(f"option-chain snapshot is stale at {decision.isoformat()}")

        contracts = tuple(
            sorted(snapshot.contracts, key=lambda item: (item.strike, item.option_type.value))
        )
        calls = {item.strike for item in contracts if item.option_type == OptionType.CALL}
        puts = {item.strike for item in contracts if item.option_type == OptionType.PUT}
        quoted = sum(1 for item in contracts if item.bid > 0 and item.ask > 0)
        quoted_fraction = quoted / len(contracts)
        paired = len(calls & puts)
        if len(contracts) < policy.min_contracts:
            raise ValueError("option-chain snapshot has insufficient contracts")
        if policy.require_call_and_put and (not calls or not puts):
            raise ValueError("option-chain snapshot must contain calls and puts")
        if paired < policy.min_paired_strikes:
            raise ValueError("option-chain snapshot has insufficient paired strikes")
        if quoted_fraction < policy.min_quoted_contract_fraction:
            raise ValueError("option-chain snapshot has insufficient quoted coverage")

        payload = {
            "decision_at": decision.isoformat(),
            "snapshot": snapshot.model_dump(mode="json"),
            "age_seconds": age.total_seconds(),
            "call_count": len(calls),
            "put_count": len(puts),
            "paired_strikes": paired,
            "quoted_contract_fraction": quoted_fraction,
        }
        frames.append(
            OptionChainReplayFrame(
                decision_at=decision,
                snapshot_id=snapshot.snapshot_id,
                source=snapshot.source,
                source_artifact_hash=snapshot.source_artifact_hash,
                observed_at=snapshot.observed_at,
                age_seconds=age.total_seconds(),
                contracts=contracts,
                call_count=len(calls),
                put_count=len(puts),
                paired_strikes=paired,
                quoted_contract_fraction=quoted_fraction,
                content_hash=_digest(payload),
            )
        )

    replay_payload = {
        "underlying": first.underlying,
        "expiry": first.expiry.isoformat(),
        "decisions": [value.isoformat() for value in decisions],
        "policy": {
            **asdict(policy),
            "max_staleness": policy.max_staleness.total_seconds(),
        },
        "visible_snapshots": [snapshot.model_dump(mode="json") for snapshot in eligible],
        "frame_hashes": [frame.content_hash for frame in frames],
    }
    return OptionChainReplayResult(
        underlying=first.underlying,
        expiry=first.expiry,
        frames=tuple(frames),
        replay_hash=_digest(replay_payload),
    )


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
