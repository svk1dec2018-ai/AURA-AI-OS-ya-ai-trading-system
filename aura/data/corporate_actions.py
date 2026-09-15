from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.domain.models import NormalizedCandle


class SplitCorporateAction(BaseModel):
    """A provenance-bound split or reverse-split observation."""

    model_config = ConfigDict(frozen=True)

    action_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    effective_at: datetime
    observed_at: datetime
    new_shares_per_old_share: Decimal = Field(gt=0)
    source: str = Field(min_length=1)
    source_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("action_id", "source")
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("corporate-action text fields must not be blank")
        return normalized

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("corporate-action symbol must not be blank")
        return normalized

    @field_validator("effective_at", "observed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("corporate-action timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_finite_ratio(self) -> SplitCorporateAction:
        if not self.new_shares_per_old_share.is_finite():
            raise ValueError("split ratio must be finite")
        return self


class AppliedSplitAdjustment(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    effective_at: datetime
    observed_at: datetime
    new_shares_per_old_share: Decimal = Field(gt=0)
    affected_candles: int = Field(ge=0)
    source: str
    source_artifact_hash: str


class CorporateActionAdjustedSeries(BaseModel):
    """Auditable adjusted research series; not an execution-price series."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    venue: str
    timeframe: str
    as_of: datetime
    original_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjusted_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candles: tuple[NormalizedCandle, ...]
    applied_actions: tuple[AppliedSplitAdjustment, ...]
    deferred_action_ids: tuple[str, ...]


def adjust_historical_candles_for_splits(
    candles: list[NormalizedCandle] | tuple[NormalizedCandle, ...],
    actions: list[SplitCorporateAction] | tuple[SplitCorporateAction, ...],
    *,
    as_of: datetime,
) -> CorporateActionAdjustedSeries:
    """Normalize a closed equity series to the latest point-in-time-known share basis."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("corporate-action as_of must be timezone-aware")
    series = tuple(candles)
    if not series:
        raise ValueError("corporate-action adjustment requires at least one candle")
    _validate_series(series, as_of=as_of)

    symbol = series[0].symbol.strip().upper()
    by_id: dict[str, SplitCorporateAction] = {}
    for action in actions:
        if action.action_id in by_id:
            raise ValueError(f"duplicate corporate action_id: {action.action_id}")
        if action.symbol != symbol:
            raise ValueError(
                f"corporate action symbol {action.symbol} does not match candle symbol {symbol}"
            )
        by_id[action.action_id] = action

    ordered_actions = tuple(
        sorted(by_id.values(), key=lambda item: (item.effective_at, item.action_id))
    )
    active = tuple(
        action
        for action in ordered_actions
        if action.observed_at <= as_of and action.effective_at <= as_of
    )
    deferred = tuple(
        action.action_id
        for action in ordered_actions
        if action.observed_at > as_of or action.effective_at > as_of
    )
    _reject_boundary_crossings(series, active)

    adjusted: list[NormalizedCandle] = []
    affected_counts = {action.action_id: 0 for action in active}
    for candle in series:
        factor = Decimal(1)
        for action in active:
            if candle.close_time <= action.effective_at:
                factor *= action.new_shares_per_old_share
                affected_counts[action.action_id] += 1
        if factor == 1:
            adjusted.append(candle)
            continue
        adjusted.append(
            candle.model_copy(
                update={
                    "open": candle.open / factor,
                    "high": candle.high / factor,
                    "low": candle.low / factor,
                    "close": candle.close / factor,
                    "volume": candle.volume * factor,
                }
            )
        )

    applied = tuple(
        AppliedSplitAdjustment(
            action_id=action.action_id,
            effective_at=action.effective_at,
            observed_at=action.observed_at,
            new_shares_per_old_share=action.new_shares_per_old_share,
            affected_candles=affected_counts[action.action_id],
            source=action.source,
            source_artifact_hash=action.source_artifact_hash,
        )
        for action in active
    )
    adjusted_series = tuple(adjusted)
    return CorporateActionAdjustedSeries(
        symbol=symbol,
        venue=series[0].venue,
        timeframe=series[0].timeframe,
        as_of=as_of,
        original_content_hash=_hash_candles(series),
        adjusted_content_hash=_hash_candles(adjusted_series),
        action_set_hash=_hash_actions(ordered_actions, as_of=as_of),
        candles=adjusted_series,
        applied_actions=applied,
        deferred_action_ids=deferred,
    )


def _validate_series(candles: tuple[NormalizedCandle, ...], *, as_of: datetime) -> None:
    first = candles[0]
    identity = (first.symbol.strip().upper(), first.venue, first.timeframe)
    previous: NormalizedCandle | None = None
    for candle in candles:
        if not candle.closed:
            raise ValueError("corporate-action adjustment accepts only closed candles")
        if (candle.symbol.strip().upper(), candle.venue, candle.timeframe) != identity:
            raise ValueError("corporate-action series must have one symbol, venue and timeframe")
        if candle.close_time > as_of:
            raise ValueError("candle closes after corporate-action as_of")
        if previous is not None:
            if candle.open_time <= previous.open_time:
                raise ValueError("corporate-action candles must be strictly chronological")
            if candle.open_time < previous.close_time:
                raise ValueError("corporate-action candles must not overlap")
        previous = candle


def _reject_boundary_crossings(
    candles: tuple[NormalizedCandle, ...],
    actions: tuple[SplitCorporateAction, ...],
) -> None:
    for action in actions:
        if any(candle.open_time < action.effective_at < candle.close_time for candle in candles):
            raise ValueError(
                f"candle crosses corporate-action boundary for action {action.action_id}"
            )


def _hash_candles(candles: tuple[NormalizedCandle, ...]) -> str:
    payload = [candle.model_dump(mode="json") for candle in candles]
    return _canonical_hash(payload)


def _hash_actions(actions: tuple[SplitCorporateAction, ...], *, as_of: datetime) -> str:
    payload = {
        "as_of": as_of.isoformat(),
        "actions": [action.model_dump(mode="json") for action in actions],
    }
    return _canonical_hash(payload)


def _canonical_hash(payload: object) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
