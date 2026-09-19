from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aura.data.futures_roll import (
    FuturesContractMetadata,
    FuturesRollEvent,
    stitch_futures_contracts,
)
from aura.domain.models import NormalizedCandle

START = datetime(2026, 1, 1, tzinfo=UTC)


def _contract(index: int, *, expiry_day: int) -> FuturesContractMetadata:
    return FuturesContractMetadata(
        contract_id=f"NIFTY-{index}",
        symbol=f"NIFTY26{index:02d}FUT",
        underlying="nifty",
        venue="nse",
        expiry_at=START + timedelta(days=expiry_day),
        observed_at=START - timedelta(days=30),
        source="NSE instrument master",
        source_artifact_hash=str(index) * 64,
    )


def _roll(
    index: int,
    *,
    roll_day: int,
    observed_day: int | None = None,
) -> FuturesRollEvent:
    return FuturesRollEvent(
        event_id=f"roll-{index}-{index + 1}",
        from_contract_id=f"NIFTY-{index}",
        to_contract_id=f"NIFTY-{index + 1}",
        roll_at=START + timedelta(days=roll_day),
        observed_at=START + timedelta(days=observed_day if observed_day is not None else 1),
        rule_id="calendar-five-days-before-expiry-v1",
        source="precommitted research manifest",
        source_artifact_hash="a" * 64,
    )


def _candle(contract: int, day: int, price: str, *, close_days: int = 1) -> NormalizedCandle:
    opened = START + timedelta(days=day)
    value = Decimal(price)
    return NormalizedCandle(
        symbol=f"NIFTY26{contract:02d}FUT",
        venue="NSE",
        timeframe="1d",
        open_time=opened,
        close_time=opened + timedelta(days=close_days),
        open=value,
        high=value + Decimal(10),
        low=value - Decimal(10),
        close=value + Decimal(5),
        volume=Decimal(1000),
    )


def _two_contract_input():
    contracts = (_contract(1, expiry_day=10), _contract(2, expiry_day=20))
    rolls = (_roll(1, roll_day=7),)
    series = {
        "NIFTY-1": (_candle(1, 5, "22000"), _candle(1, 6, "22050")),
        "NIFTY-2": (_candle(2, 7, "22100"), _candle(2, 8, "22150")),
    }
    return contracts, rolls, series


def test_stitch_preserves_actual_contract_prices_and_marks_roll_reset() -> None:
    contracts, rolls, series = _two_contract_input()
    result = stitch_futures_contracts(
        contracts,
        rolls,
        series,
        as_of=START + timedelta(days=9),
    )

    assert result.active_contract_id == "NIFTY-2"
    assert result.price_adjustment_applied is False
    assert [item.contract_id for item in result.candles] == [
        "NIFTY-1",
        "NIFTY-1",
        "NIFTY-2",
        "NIFTY-2",
    ]
    assert [item.return_reset for item in result.candles] == [True, False, True, False]
    assert [item.candle.open for item in result.candles] == [
        Decimal(22000),
        Decimal(22050),
        Decimal(22100),
        Decimal(22150),
    ]


def test_roll_boundary_reports_raw_gap_without_treating_it_as_return() -> None:
    contracts, rolls, series = _two_contract_input()
    result = stitch_futures_contracts(
        contracts,
        rolls,
        series,
        as_of=START + timedelta(days=9),
    )

    boundary = result.boundaries[0]
    assert boundary.from_last_close == Decimal(22055)
    assert boundary.to_first_open == Decimal(22100)
    assert boundary.raw_price_gap == Decimal(45)
    assert boundary.raw_price_ratio == Decimal(22100) / Decimal(22055)
    assert boundary.return_reset is True


def test_future_roll_is_deferred_and_future_contract_data_is_not_accepted() -> None:
    contracts, rolls, _series = _two_contract_input()
    first_series = {"NIFTY-1": (_candle(1, 4, "21900"), _candle(1, 5, "22000"))}
    result = stitch_futures_contracts(
        contracts,
        rolls,
        first_series,
        as_of=START + timedelta(days=6),
    )

    assert result.active_contract_id == "NIFTY-1"
    assert result.deferred_roll_ids == ("roll-1-2",)
    assert result.boundaries == ()
    with pytest.raises(ValueError, match="exactly the point-in-time active chain"):
        stitch_futures_contracts(
            contracts,
            rolls,
            {**first_series, "NIFTY-2": (_candle(2, 5, "22100"),)},
            as_of=START + timedelta(days=6),
        )


def test_roll_rule_must_be_observed_before_transition() -> None:
    with pytest.raises(ValidationError, match="observed no later"):
        _roll(1, roll_day=7, observed_day=8)


def test_roll_after_expiry_is_rejected() -> None:
    with pytest.raises(ValueError, match="before outgoing contract expiry"):
        stitch_futures_contracts(
            (_contract(1, expiry_day=7), _contract(2, expiry_day=20)),
            (_roll(1, roll_day=7),),
            {"NIFTY-1": (_candle(1, 5, "22000"),)},
            as_of=START + timedelta(days=6),
        )


def test_missing_roll_after_expiry_fails_closed() -> None:
    with pytest.raises(ValueError, match="no eligible roll before contract expiry"):
        stitch_futures_contracts(
            (_contract(1, expiry_day=7),),
            (),
            {"NIFTY-1": (_candle(1, 5, "22000"),)},
            as_of=START + timedelta(days=8),
        )


def test_non_adjacent_roll_is_rejected() -> None:
    contracts = (
        _contract(1, expiry_day=10),
        _contract(2, expiry_day=20),
        _contract(3, expiry_day=30),
    )
    bad_roll = _roll(1, roll_day=7).model_copy(update={"to_contract_id": "NIFTY-3"})
    with pytest.raises(ValueError, match="next declared expiry"):
        stitch_futures_contracts(
            contracts,
            (bad_roll,),
            {"NIFTY-1": (_candle(1, 5, "22000"),)},
            as_of=START + timedelta(days=6),
        )


def test_candle_crossing_roll_boundary_is_rejected() -> None:
    contracts, rolls, series = _two_contract_input()
    series["NIFTY-1"] = (_candle(1, 6, "22000", close_days=2),)
    with pytest.raises(ValueError, match="crosses outgoing roll boundary"):
        stitch_futures_contracts(
            contracts,
            rolls,
            series,
            as_of=START + timedelta(days=9),
        )


def test_future_or_wrong_contract_candle_is_rejected() -> None:
    contracts, rolls, series = _two_contract_input()
    series["NIFTY-2"] = (_candle(2, 9, "22100"),)
    with pytest.raises(ValueError, match="closes after roll as_of"):
        stitch_futures_contracts(
            contracts,
            rolls,
            series,
            as_of=START + timedelta(days=9),
        )

    contracts, rolls, series = _two_contract_input()
    series["NIFTY-2"] = (_candle(2, 7, "22100").model_copy(update={"symbol": "BANKNIFTY26FUT"}),)
    with pytest.raises(ValueError, match="identity does not match"):
        stitch_futures_contracts(
            contracts,
            rolls,
            series,
            as_of=START + timedelta(days=9),
        )


def test_unobserved_active_contract_metadata_is_rejected() -> None:
    contract = _contract(1, expiry_day=10).model_copy(
        update={"observed_at": START + timedelta(days=5)}
    )
    with pytest.raises(ValueError, match="metadata is not yet observed"):
        stitch_futures_contracts(
            (contract,),
            (),
            {"NIFTY-1": (_candle(1, 1, "22000"),)},
            as_of=START + timedelta(days=2),
        )


def test_roll_content_hash_is_deterministic_and_price_sensitive() -> None:
    contracts, rolls, series = _two_contract_input()
    first = stitch_futures_contracts(
        contracts,
        rolls,
        series,
        as_of=START + timedelta(days=9),
    )
    second = stitch_futures_contracts(
        contracts,
        rolls,
        series,
        as_of=START + timedelta(days=9),
    )
    changed = dict(series)
    changed["NIFTY-2"] = (_candle(2, 7, "22200"), _candle(2, 8, "22150"))
    third = stitch_futures_contracts(
        contracts,
        rolls,
        changed,
        as_of=START + timedelta(days=9),
    )

    assert first == second
    assert first.content_hash != third.content_hash
