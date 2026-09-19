from __future__ import annotations

import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from aura.domain.models import Fill, NormalizedCandle, OrderRequest, PortfolioSnapshot, Tick
from aura.portfolio.ledger import Position


class CoreEntity(str, Enum):
    TICK = "tick"
    CANDLE = "candle"
    ORDER = "order"
    FILL = "fill"
    POSITION = "position"
    PORTFOLIO = "portfolio"


class CoreContractEnvelope(BaseModel):
    """Versioned wire envelope for persisted or inter-service core entities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    entity: CoreEntity
    payload: dict[str, Any]


_CORE_TYPES: dict[CoreEntity, type[Any]] = {
    CoreEntity.TICK: Tick,
    CoreEntity.CANDLE: NormalizedCandle,
    CoreEntity.ORDER: OrderRequest,
    CoreEntity.FILL: Fill,
    CoreEntity.POSITION: Position,
    CoreEntity.PORTFOLIO: PortfolioSnapshot,
}
_ADAPTERS = {entity: TypeAdapter(model) for entity, model in _CORE_TYPES.items()}


def encode_core_entity(value: object) -> bytes:
    """Serialize a supported entity to canonical, finite JSON bytes."""

    entity = next(
        (candidate for candidate, model in _CORE_TYPES.items() if isinstance(value, model)),
        None,
    )
    if entity is None:
        raise TypeError(f"unsupported core entity type: {type(value).__name__}")
    payload = _ADAPTERS[entity].dump_python(value, mode="json")
    envelope = CoreContractEnvelope(
        schema_version=1,
        entity=entity,
        payload=payload,
    )
    return json.dumps(
        envelope.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def decode_core_entity(
    encoded: bytes | str,
    *,
    expected_entity: CoreEntity | None = None,
) -> object:
    """Validate and deserialize one versioned core entity envelope."""

    try:
        raw = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("core entity envelope is not valid JSON") from exc
    envelope = CoreContractEnvelope.model_validate(raw)
    if expected_entity is not None and envelope.entity is not expected_entity:
        raise ValueError(
            f"core entity mismatch: expected {expected_entity.value}, got {envelope.entity.value}"
        )
    return _ADAPTERS[envelope.entity].validate_python(envelope.payload)


def core_contract_schemas() -> dict[CoreEntity, dict[str, Any]]:
    """Return deterministic JSON schemas for all mandatory Phase-1 entities."""

    return {
        entity: adapter.json_schema()
        for entity, adapter in sorted(_ADAPTERS.items(), key=lambda item: item[0].value)
    }
