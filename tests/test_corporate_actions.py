from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aura.data.corporate_actions import (
    SplitCorporateAction,
    adjust_historical_candles_for_splits,
)
from aura.domain.models import NormalizedCandle

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(index: int, price: str, *, closed: bool = True) -> NormalizedCandle:
    opened = START + timedelta(days=index)
    value = Decimal(price)
    return NormalizedCandle(
        symbol="RELIANCE",
        venue="NSE",
        timeframe="1d",
        open_time=opened,
        close_time=opened + timedelta(days=1),
        open=value,
        high=value + Decimal(10),
        low=value - Decimal(10),
        close=value + Decimal(5),
        volume=Decimal(100),
        closed=closed,
    )


def _split(
    action_id: str,
    *,
    effective_day: int,
    ratio: str = "2",
    observed_day: int | None = None,
) -> SplitCorporateAction:
    effective = START + timedelta(days=effective_day)
    observed = START + timedelta(
        days=observed_day if observed_day is not None else effective_day - 1
    )
    return SplitCorporateAction(
        action_id=action_id,
        symbol="reliance",
        effective_at=effective,
        observed_at=observed,
        new_shares_per_old_share=Decimal(ratio),
        source="NSE corporate-action file",
        source_artifact_hash="a" * 64,
    )


def test_two_for_one_split_adjusts_only_pre_effective_candles() -> None:
    original = (_candle(0, "1000"), _candle(1, "1100"), _candle(2, "600"))
    result = adjust_historical_candles_for_splits(
        original,
        (_split("split-2x", effective_day=2),),
        as_of=START + timedelta(days=4),
    )

    assert [item.open for item in result.candles] == [Decimal(500), Decimal(550), Decimal(600)]
    assert [item.volume for item in result.candles] == [Decimal(200), Decimal(200), Decimal(100)]
    assert result.applied_actions[0].affected_candles == 2
    assert result.deferred_action_ids == ()
    assert original[0].open == Decimal(1000)


def test_reverse_split_increases_pre_effective_price_and_reduces_volume() -> None:
    result = adjust_historical_candles_for_splits(
        (_candle(0, "50"), _candle(1, "120")),
        (_split("reverse", effective_day=1, ratio="0.5"),),
        as_of=START + timedelta(days=3),
    )

    assert result.candles[0].open == Decimal(100)
    assert result.candles[0].volume == Decimal(50)
    assert result.candles[1].open == Decimal(120)


def test_multiple_known_splits_compound_deterministically() -> None:
    result = adjust_historical_candles_for_splits(
        (_candle(0, "1200"), _candle(1, "700"), _candle(2, "400")),
        (
            _split("later", effective_day=2, ratio="2"),
            _split("earlier", effective_day=1, ratio="3"),
        ),
        as_of=START + timedelta(days=4),
    )

    assert [item.open for item in result.candles] == [Decimal(200), Decimal(350), Decimal(400)]
    assert [item.action_id for item in result.applied_actions] == ["earlier", "later"]


def test_future_or_not_yet_observed_action_is_deferred_without_adjustment() -> None:
    candles = (_candle(0, "1000"), _candle(1, "1100"))
    result = adjust_historical_candles_for_splits(
        candles,
        (
            _split("future-effective", effective_day=5, observed_day=1),
            _split("late-observation", effective_day=1, observed_day=4),
        ),
        as_of=START + timedelta(days=3),
    )

    assert result.candles == candles
    assert result.applied_actions == ()
    assert result.deferred_action_ids == ("late-observation", "future-effective")
    assert result.original_content_hash == result.adjusted_content_hash


def test_hashes_bind_input_actions_and_as_of() -> None:
    candles = (_candle(0, "1000"), _candle(1, "600"))
    action = _split("split", effective_day=1)
    first = adjust_historical_candles_for_splits(
        candles,
        (action,),
        as_of=START + timedelta(days=3),
    )
    second = adjust_historical_candles_for_splits(
        candles,
        (action,),
        as_of=START + timedelta(days=3),
    )
    later = adjust_historical_candles_for_splits(
        candles,
        (action,),
        as_of=START + timedelta(days=4),
    )

    assert first == second
    assert first.original_content_hash != first.adjusted_content_hash
    assert first.action_set_hash != later.action_set_hash


def test_duplicate_action_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate corporate action_id"):
        adjust_historical_candles_for_splits(
            (_candle(0, "1000"),),
            (_split("same", effective_day=1), _split("same", effective_day=2)),
            as_of=START + timedelta(days=3),
        )


def test_mismatched_action_symbol_is_rejected() -> None:
    action = _split("wrong-symbol", effective_day=1).model_copy(update={"symbol": "TCS"})
    with pytest.raises(ValueError, match="does not match candle symbol"):
        adjust_historical_candles_for_splits(
            (_candle(0, "1000"),),
            (action,),
            as_of=START + timedelta(days=2),
        )


def test_candle_crossing_effective_boundary_is_rejected() -> None:
    candle = _candle(0, "1000").model_copy(update={"close_time": START + timedelta(days=2)})
    action = _split("intrabar", effective_day=1)
    with pytest.raises(ValueError, match="crosses corporate-action boundary"):
        adjust_historical_candles_for_splits(
            (candle,),
            (action,),
            as_of=START + timedelta(days=3),
        )


def test_future_or_open_candle_cannot_enter_adjustment() -> None:
    with pytest.raises(ValueError, match="closes after"):
        adjust_historical_candles_for_splits(
            (_candle(1, "1000"),),
            (),
            as_of=START + timedelta(days=1, hours=12),
        )
    with pytest.raises(ValueError, match="only closed candles"):
        adjust_historical_candles_for_splits(
            (_candle(0, "1000", closed=False),),
            (),
            as_of=START + timedelta(days=2),
        )


def test_mixed_or_overlapping_series_is_rejected() -> None:
    mixed = _candle(1, "1100").model_copy(update={"venue": "BSE"})
    with pytest.raises(ValueError, match="one symbol, venue and timeframe"):
        adjust_historical_candles_for_splits(
            (_candle(0, "1000"), mixed),
            (),
            as_of=START + timedelta(days=3),
        )
    overlapping = _candle(1, "1100").model_copy(update={"open_time": START + timedelta(hours=12)})
    with pytest.raises(ValueError, match="must not overlap"):
        adjust_historical_candles_for_splits(
            (_candle(0, "1000"), overlapping),
            (),
            as_of=START + timedelta(days=3),
        )


def test_split_requires_valid_provenance_and_timestamps() -> None:
    with pytest.raises(ValidationError):
        SplitCorporateAction(
            action_id="bad-hash",
            symbol="RELIANCE",
            effective_at=START + timedelta(days=1),
            observed_at=START,
            new_shares_per_old_share=Decimal(2),
            source="NSE",
            source_artifact_hash="not-a-hash",
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        SplitCorporateAction(
            action_id="naive",
            symbol="RELIANCE",
            effective_at=START.replace(tzinfo=None),
            observed_at=START,
            new_shares_per_old_share=Decimal(2),
            source="NSE",
            source_artifact_hash="b" * 64,
        )
