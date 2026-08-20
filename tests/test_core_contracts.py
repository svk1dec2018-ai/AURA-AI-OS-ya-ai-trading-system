from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from aura.domain.models import Fill, OrderRequest, OrderType, Side, Tick
from aura.domain.serialization import CoreEntity, decode_core_entity, encode_core_entity
from aura.ops.core_contracts import (
    build_core_contract_artifacts,
    check_core_contract_artifacts,
)


def test_core_entities_round_trip_through_versioned_canonical_envelope() -> None:
    tick = Tick(
        symbol="BTC-USD",
        venue="COINBASE_PUBLIC",
        price=Decimal("60000.25"),
        quantity=Decimal("0.1"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )

    encoded = encode_core_entity(tick)
    decoded = decode_core_entity(encoded, expected_entity=CoreEntity.TICK)

    assert decoded == tick
    assert encoded == json.dumps(
        json.loads(encoded),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with pytest.raises(ValueError, match="entity mismatch"):
        decode_core_entity(encoded, expected_entity=CoreEntity.FILL)


def test_order_contract_rejects_ambiguous_price_and_timestamp_semantics() -> None:
    common = {
        "symbol": "X",
        "venue": "TEST",
        "side": Side.BUY,
        "quantity": Decimal(1),
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    with pytest.raises(ValidationError, match="market order cannot"):
        OrderRequest(**common, limit_price=Decimal(1))
    with pytest.raises(ValidationError, match="positive limit_price"):
        OrderRequest(**common, order_type=OrderType.LIMIT)
    with pytest.raises(ValidationError, match="timezone-aware"):
        OrderRequest(**{**common, "created_at": common["created_at"].replace(tzinfo=None)})


def test_fill_and_tick_contracts_reject_unknown_or_naive_input() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Tick(
            symbol="X",
            venue="TEST",
            price=Decimal(1),
            timestamp=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Fill.model_validate(
            {
                "fill_id": "fill",
                "order_id": "order",
                "symbol": "X",
                "side": "BUY",
                "quantity": "1",
                "price": "1",
                "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
                "unrecognized": "value",
            }
        )


def test_phase_one_reports_cover_every_required_entity_and_are_current() -> None:
    schema_report, suite = build_core_contract_artifacts()
    assert schema_report["decision"] == "PASS"
    assert schema_report["entity_count"] == 6
    assert schema_report["required_entities"] == [
        "candle",
        "fill",
        "order",
        "portfolio",
        "position",
        "tick",
    ]
    assert all(item["additional_properties"] is False for item in schema_report["entities"])
    assert suite["all_cases_passed"] is True
    assert len(suite["round_trip_cases"]) == 6
    assert len(suite["rejection_cases"]) == 7

    root = Path(__file__).resolve().parents[1]
    assert check_core_contract_artifacts(root) == ()
