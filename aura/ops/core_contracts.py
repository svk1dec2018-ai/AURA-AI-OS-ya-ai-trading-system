from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from aura.domain.models import (
    Fill,
    NormalizedCandle,
    OrderRequest,
    OrderType,
    PortfolioSnapshot,
    Side,
    Tick,
)
from aura.domain.serialization import (
    CoreEntity,
    core_contract_schemas,
    decode_core_entity,
    encode_core_entity,
)
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.portfolio.ledger import Position

OUTPUT_DIR = Path("artifacts/governance")
SCHEMA_REPORT = OUTPUT_DIR / "core_contract_schema_report.json"
VALIDATION_SUITE = OUTPUT_DIR / "core_contract_validation_suite.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_ONE_EVIDENCE = {
    "Schema test report": SCHEMA_REPORT.as_posix(),
    "Contract validation suite": VALIDATION_SUITE.as_posix(),
}
_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def build_core_contract_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    fixtures = _fixtures()
    schemas = core_contract_schemas()
    expected = set(CoreEntity)
    if set(fixtures) != expected or set(schemas) != expected:
        raise RuntimeError("mandatory Phase-1 core entity coverage is incomplete")

    entities: list[dict[str, Any]] = []
    round_trip_cases: list[dict[str, Any]] = []
    for entity in sorted(expected, key=lambda item: item.value):
        schema = schemas[entity]
        if schema.get("additionalProperties") is not False:
            raise RuntimeError(f"{entity.value} schema does not reject ambiguous fields")
        encoded = encode_core_entity(fixtures[entity])
        decoded = decode_core_entity(encoded, expected_entity=entity)
        if decoded != fixtures[entity]:
            raise RuntimeError(f"{entity.value} canonical round trip changed the entity")
        canonical = json.dumps(
            json.loads(encoded),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if canonical != encoded:
            raise RuntimeError(f"{entity.value} serialization is not canonical")
        schema_bytes = _canonical_json(schema)
        entities.append(
            {
                "entity": entity.value,
                "model": f"{type(fixtures[entity]).__module__}.{type(fixtures[entity]).__name__}",
                "additional_properties": False,
                "json_schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
                "required_fields": sorted(schema.get("required", [])),
            }
        )
        round_trip_cases.append(
            {
                "case": f"{entity.value}_canonical_round_trip",
                "passed": True,
                "encoded_sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )

    rejection_cases = _run_rejection_cases()
    return (
        {
            "schema_version": 1,
            "phase": 1,
            "decision": "PASS",
            "required_entities": [item.value for item in sorted(expected, key=lambda x: x.value)],
            "entity_count": len(entities),
            "ambiguous_fields_allowed": False,
            "entities": entities,
        },
        {
            "schema_version": 1,
            "phase": 1,
            "decision": "PASS",
            "serialization": "versioned canonical JSON envelope",
            "round_trip_cases": round_trip_cases,
            "rejection_cases": rejection_cases,
            "all_cases_passed": True,
        },
    )


def write_core_contract_artifacts(root: Path) -> None:
    root = root.resolve()
    schema_report, validation_suite = build_core_contract_artifacts()
    _write_json(root / SCHEMA_REPORT, schema_report)
    _write_json(root / VALIDATION_SUITE, validation_suite)
    records = build_sequential_phase_records(
        root,
        {
            0: PHASE_ZERO_EVIDENCE,
            1: PHASE_ONE_EVIDENCE,
        },
    )
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_core_contract_artifacts(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    schema_report, validation_suite = build_core_contract_artifacts()
    expected = {
        SCHEMA_REPORT: _pretty_json(schema_report),
        VALIDATION_SUITE: _pretty_json(validation_suite),
    }
    errors: list[str] = []
    for relative, content in expected.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing Phase 1 evidence: {relative.as_posix()}")
        elif path.read_text(encoding="utf-8") != content:
            errors.append(f"stale Phase 1 evidence: {relative.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 1):
        errors.append("Phase 1 is not PASS in the governance ledger")
    return tuple(errors)


def _fixtures() -> dict[CoreEntity, object]:
    return {
        CoreEntity.TICK: Tick(
            symbol="BTC-USD",
            venue="COINBASE_PUBLIC",
            price=Decimal("60000.25"),
            quantity=Decimal("0.1"),
            timestamp=_NOW,
        ),
        CoreEntity.CANDLE: NormalizedCandle(
            symbol="BTC-USD",
            venue="COINBASE_PUBLIC",
            timeframe="5m",
            open_time=_NOW,
            close_time=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
            open=Decimal(60000),
            high=Decimal(60100),
            low=Decimal(59900),
            close=Decimal(60050),
            volume=Decimal("12.5"),
        ),
        CoreEntity.ORDER: OrderRequest(
            order_id="order-1",
            client_order_id="client-1",
            symbol="BTC-USD",
            venue="AURA_PAPER",
            side=Side.BUY,
            quantity=Decimal("0.1"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal(60000),
            created_at=_NOW,
        ),
        CoreEntity.FILL: Fill(
            fill_id="fill-1",
            order_id="order-1",
            symbol="BTC-USD",
            side=Side.BUY,
            quantity=Decimal("0.1"),
            price=Decimal(60000),
            fee=Decimal("1.25"),
            timestamp=_NOW,
        ),
        CoreEntity.POSITION: Position(
            symbol="BTC-USD",
            quantity=Decimal("0.1"),
            average_price=Decimal(60000),
            realized_pnl=Decimal("12.5"),
        ),
        CoreEntity.PORTFOLIO: PortfolioSnapshot(
            cash=Decimal(40000),
            equity=Decimal(100000),
            gross_exposure=Decimal(6000),
            net_exposure=Decimal(6000),
            realized_pnl=Decimal("12.5"),
            unrealized_pnl=Decimal(5),
            peak_equity=Decimal(100100),
            drawdown_pct=Decimal("0.0999000999"),
            position_values={"BTC-USD": Decimal(6000)},
        ),
    }


def _run_rejection_cases() -> list[dict[str, Any]]:
    cases: tuple[tuple[str, Callable[[], object]], ...] = (
        (
            "tick_rejects_naive_timestamp",
            lambda: Tick(
                symbol="X",
                venue="TEST",
                price=Decimal(1),
                timestamp=_NOW.replace(tzinfo=None),
            ),
        ),
        (
            "candle_rejects_unknown_field",
            lambda: NormalizedCandle.model_validate(
                {**_fixtures()[CoreEntity.CANDLE].model_dump(), "unknown": "value"}
            ),
        ),
        (
            "market_order_rejects_limit_price",
            lambda: OrderRequest(
                symbol="X",
                venue="TEST",
                side=Side.BUY,
                quantity=Decimal(1),
                limit_price=Decimal(1),
                created_at=_NOW,
            ),
        ),
        (
            "fill_rejects_naive_timestamp",
            lambda: Fill(
                fill_id="fill",
                order_id="order",
                symbol="X",
                side=Side.BUY,
                quantity=Decimal(1),
                price=Decimal(1),
                timestamp=_NOW.replace(tzinfo=None),
            ),
        ),
        (
            "position_rejects_unknown_field",
            lambda: Position.model_validate({"symbol": "X", "unknown": 1}),
        ),
        (
            "portfolio_rejects_negative_gross_exposure",
            lambda: PortfolioSnapshot.model_validate(
                {
                    **_fixtures()[CoreEntity.PORTFOLIO].model_dump(),
                    "gross_exposure": Decimal(-1),
                }
            ),
        ),
        (
            "envelope_rejects_entity_confusion",
            lambda: decode_core_entity(
                encode_core_entity(_fixtures()[CoreEntity.TICK]),
                expected_entity=CoreEntity.FILL,
            ),
        ),
    )
    results: list[dict[str, Any]] = []
    for name, operation in cases:
        try:
            operation()
        except (TypeError, ValueError):
            results.append({"case": name, "passed": True})
        else:
            raise RuntimeError(f"negative contract case unexpectedly passed: {name}")
    return results


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-1 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_core_contract_artifacts(root)
        print("Phase 1: PASS")
        return 0
    errors = check_core_contract_artifacts(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 1 contract artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
