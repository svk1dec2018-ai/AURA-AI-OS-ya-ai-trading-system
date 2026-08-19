import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aura.data.options_replay import (
    OptionChainReplayPolicy,
    OptionChainSnapshot,
    replay_option_chain,
)
from aura.markets.universe import OptionType
from aura.options.intelligence import OptionContractObservation, OptionGreeks

START = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
EXPIRY = START + timedelta(days=7)
ARTIFACT_HASH = "a" * 64


def _contract(
    side: OptionType,
    strike: int,
    observed_at: datetime,
    *,
    oi: int = 100,
    bid: str = "99",
    ask: str = "101",
) -> OptionContractObservation:
    return OptionContractObservation(
        underlying="NIFTY",
        expiry=EXPIRY,
        strike=Decimal(strike),
        option_type=side,
        spot=Decimal(25000),
        last_price=Decimal(100),
        bid=Decimal(bid),
        ask=Decimal(ask),
        open_interest=Decimal(oi),
        volume=Decimal(20),
        implied_volatility=0.2,
        greeks=OptionGreeks(delta=0.5, gamma=0.001, theta=-4, vega=9),
        observed_at=observed_at,
    )


def _snapshot(minute: int, *, oi: int = 100, snapshot_id: str | None = None):
    observed_at = START + timedelta(minutes=minute)
    return OptionChainSnapshot(
        snapshot_id=snapshot_id or f"chain-{minute}",
        source="authorized-archive",
        source_artifact_hash=ARTIFACT_HASH,
        underlying="nifty",
        expiry=EXPIRY,
        observed_at=observed_at,
        contracts=(
            _contract(OptionType.PUT, 25000, observed_at, oi=oi),
            _contract(OptionType.CALL, 25100, observed_at, oi=oi),
            _contract(OptionType.CALL, 25000, observed_at, oi=oi),
            _contract(OptionType.PUT, 25100, observed_at, oi=oi),
        ),
    )


def test_replay_selects_latest_visible_exact_snapshot() -> None:
    result = replay_option_chain(
        [_snapshot(2, oi=222), _snapshot(0, oi=100)],
        [START + timedelta(minutes=1), START + timedelta(minutes=3)],
    )

    assert [frame.snapshot_id for frame in result.frames] == ["chain-0", "chain-2"]
    assert result.frames[1].age_seconds == 60
    assert result.frames[1].paired_strikes == 2
    assert result.frames[1].contracts[0].open_interest == Decimal(222)
    assert [item.strike for item in result.frames[1].contracts] == [
        Decimal(25000),
        Decimal(25000),
        Decimal(25100),
        Decimal(25100),
    ]


def test_future_snapshot_cannot_change_earlier_replay_or_hash() -> None:
    decision = START + timedelta(minutes=1)
    baseline = replay_option_chain([_snapshot(0)], [decision])
    with_future = replay_option_chain([_snapshot(0), _snapshot(10, oi=999999)], [decision])

    assert with_future == baseline


def test_replay_is_deterministic_and_recorded_change_updates_hash() -> None:
    decision = START + timedelta(minutes=1)
    first = replay_option_chain([_snapshot(0)], [decision])
    repeated = replay_option_chain([_snapshot(0)], [decision])
    changed = replay_option_chain([_snapshot(0, oi=101)], [decision])

    assert first.replay_hash == repeated.replay_hash
    assert first.frames[0].content_hash == repeated.frames[0].content_hash
    assert changed.replay_hash != first.replay_hash


def test_missing_or_stale_visible_snapshot_fails_closed() -> None:
    with pytest.raises(ValueError, match="no visible"):
        replay_option_chain([_snapshot(2)], [START + timedelta(minutes=1)])
    with pytest.raises(ValueError, match="stale"):
        replay_option_chain(
            [_snapshot(0)],
            [START + timedelta(minutes=6)],
            policy=OptionChainReplayPolicy(max_staleness=timedelta(minutes=5)),
        )


def test_incomplete_chain_coverage_fails_closed() -> None:
    observed_at = START
    calls_only = _snapshot(0).model_copy(
        update={
            "contracts": (
                _contract(OptionType.CALL, 25000, observed_at),
                _contract(OptionType.CALL, 25100, observed_at),
            )
        }
    )
    unpaired = _snapshot(0).model_copy(
        update={
            "contracts": (
                _contract(OptionType.CALL, 25000, observed_at),
                _contract(OptionType.PUT, 25100, observed_at),
            )
        }
    )

    with pytest.raises(ValueError, match="calls and puts"):
        replay_option_chain([calls_only], [START + timedelta(minutes=1)])
    with pytest.raises(ValueError, match="paired strikes"):
        replay_option_chain([unpaired], [START + timedelta(minutes=1)])


def test_insufficient_two_sided_quote_coverage_fails_closed() -> None:
    observed_at = START
    snapshot = _snapshot(0).model_copy(
        update={
            "contracts": (
                _contract(OptionType.CALL, 25000, observed_at, bid="0", ask="0"),
                _contract(OptionType.PUT, 25000, observed_at, bid="0", ask="0"),
            )
        }
    )
    with pytest.raises(ValueError, match="quoted coverage"):
        replay_option_chain([snapshot], [START + timedelta(minutes=1)])


def test_snapshot_rejects_duplicate_contract_and_non_atomic_timestamp() -> None:
    observed_at = START
    contract = _contract(OptionType.CALL, 25000, observed_at)
    kwargs = _snapshot(0).model_dump()
    kwargs["contracts"] = (contract, contract)
    with pytest.raises(ValidationError, match="duplicate"):
        OptionChainSnapshot(**kwargs)

    kwargs["contracts"] = (
        contract,
        _contract(OptionType.PUT, 25000, observed_at + timedelta(seconds=1)),
    )
    with pytest.raises(ValidationError, match="atomic"):
        OptionChainSnapshot(**kwargs)


def test_snapshot_rejects_inconsistent_spot_one_sided_quote_and_nonfinite_metric() -> None:
    observed_at = START
    base = _snapshot(0).model_dump()
    call = _contract(OptionType.CALL, 25000, observed_at)
    put = _contract(OptionType.PUT, 25000, observed_at)

    base["contracts"] = (call, put.model_copy(update={"spot": Decimal(25001)}))
    with pytest.raises(ValidationError, match="share spot"):
        OptionChainSnapshot(**base)

    base["contracts"] = (call, put.model_copy(update={"bid": Decimal(0)}))
    with pytest.raises(ValidationError, match="two-sided"):
        OptionChainSnapshot(**base)

    base["contracts"] = (call, put.model_copy(update={"greeks": OptionGreeks(gamma=math.nan)}))
    with pytest.raises(ValidationError, match="finite"):
        OptionChainSnapshot(**base)


def test_replay_rejects_ambiguous_or_invalid_timeline() -> None:
    duplicate_time = _snapshot(0, snapshot_id="other")
    with pytest.raises(ValueError, match="timestamps must be unique"):
        replay_option_chain([_snapshot(0), duplicate_time], [START + timedelta(minutes=1)])
    with pytest.raises(ValueError, match="timezone-aware"):
        replay_option_chain([_snapshot(0)], [START.replace(tzinfo=None)])
    with pytest.raises(ValueError, match="strictly increasing"):
        replay_option_chain(
            [_snapshot(0)],
            [START + timedelta(minutes=2), START + timedelta(minutes=1)],
        )
