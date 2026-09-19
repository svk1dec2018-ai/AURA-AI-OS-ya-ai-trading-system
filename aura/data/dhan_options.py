from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aura.data.live_plane import DataDomain, LiveDataEvent


class DhanOptionGreeks(BaseModel):
    model_config = ConfigDict(frozen=True)

    delta: float
    theta: float
    gamma: float
    vega: float


class DhanOptionContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    underlying: str = Field(min_length=1)
    expiry: str = Field(min_length=1)
    strike: Decimal
    option_type: Literal["CE", "PE"]
    security_id: int = Field(ge=0)
    average_price: float = Field(ge=0)
    implied_volatility: float = Field(ge=0)
    last_price: float = Field(ge=0)
    open_interest: int = Field(ge=0)
    previous_close_price: float = Field(ge=0)
    previous_open_interest: int = Field(ge=0)
    previous_volume: int = Field(ge=0)
    top_ask_price: float = Field(ge=0)
    top_ask_quantity: int = Field(ge=0)
    top_bid_price: float = Field(ge=0)
    top_bid_quantity: int = Field(ge=0)
    volume: int = Field(ge=0)
    greeks: DhanOptionGreeks

    @property
    def subject(self) -> str:
        return f"{self.underlying}:{self.expiry}:{self.strike}:{self.option_type}"


def parse_dhan_option_chain(
    response: dict[str, Any],
    *,
    underlying: str,
    expiry: str,
) -> tuple[DhanOptionContract, ...]:
    """Normalize the DhanHQ v2 option-chain response into typed contracts."""

    try:
        option_chain = response["data"]["oc"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Dhan option-chain response missing data.oc") from exc
    if not isinstance(option_chain, dict):
        raise TypeError("Dhan option-chain data.oc must be an object")

    contracts: list[DhanOptionContract] = []
    for strike_text, sides in option_chain.items():
        try:
            strike = Decimal(str(strike_text))
        except Exception as exc:
            raise ValueError(f"invalid Dhan option-chain strike: {strike_text}") from exc
        if not isinstance(sides, dict):
            raise TypeError(f"Dhan option-chain strike {strike_text} must contain side objects")
        for source_side, option_type in (("ce", "CE"), ("pe", "PE")):
            raw = sides.get(source_side)
            if raw is None:
                continue
            if not isinstance(raw, dict):
                raise TypeError(f"Dhan option side {source_side} at {strike_text} must be an object")
            contracts.append(
                DhanOptionContract(
                    underlying=underlying,
                    expiry=expiry,
                    strike=strike,
                    option_type=option_type,
                    security_id=int(raw["security_id"]),
                    average_price=float(raw.get("average_price", 0)),
                    implied_volatility=float(raw.get("implied_volatility", 0)),
                    last_price=float(raw.get("last_price", 0)),
                    open_interest=int(raw.get("oi", 0)),
                    previous_close_price=float(raw.get("previous_close_price", 0)),
                    previous_open_interest=int(raw.get("previous_oi", 0)),
                    previous_volume=int(raw.get("previous_volume", 0)),
                    top_ask_price=float(raw.get("top_ask_price", 0)),
                    top_ask_quantity=int(raw.get("top_ask_quantity", 0)),
                    top_bid_price=float(raw.get("top_bid_price", 0)),
                    top_bid_quantity=int(raw.get("top_bid_quantity", 0)),
                    volume=int(raw.get("volume", 0)),
                    greeks=DhanOptionGreeks.model_validate(raw.get("greeks", {})),
                )
            )
    contracts.sort(key=lambda contract: (contract.strike, contract.option_type))
    return tuple(contracts)


def dhan_option_chain_to_live_events(
    response: dict[str, Any],
    *,
    underlying: str,
    expiry: str,
    received_at: datetime,
    source_id: str = "dhan-v2-option-chain",
) -> tuple[LiveDataEvent, ...]:
    """Emit canonical option quote, Greeks and OI events for each Dhan contract."""

    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    contracts = parse_dhan_option_chain(response, underlying=underlying, expiry=expiry)
    events: list[LiveDataEvent] = []
    for contract in contracts:
        common = {
            "underlying": contract.underlying,
            "expiry": contract.expiry,
            "strike": str(contract.strike),
            "option_type": contract.option_type,
            "security_id": contract.security_id,
        }
        payloads = (
            (
                DataDomain.OPTIONS,
                {
                    **common,
                    "last_price": contract.last_price,
                    "average_price": contract.average_price,
                    "implied_volatility": contract.implied_volatility,
                    "volume": contract.volume,
                    "previous_close_price": contract.previous_close_price,
                    "previous_volume": contract.previous_volume,
                    "top_bid_price": contract.top_bid_price,
                    "top_bid_quantity": contract.top_bid_quantity,
                    "top_ask_price": contract.top_ask_price,
                    "top_ask_quantity": contract.top_ask_quantity,
                },
            ),
            (
                DataDomain.GREEKS,
                {
                    **common,
                    **contract.greeks.model_dump(mode="python"),
                    "implied_volatility": contract.implied_volatility,
                },
            ),
            (
                DataDomain.OPEN_INTEREST,
                {
                    **common,
                    "open_interest": contract.open_interest,
                    "previous_open_interest": contract.previous_open_interest,
                },
            ),
        )
        for domain, payload in payloads:
            events.append(
                LiveDataEvent(
                    event_id=(
                        f"{source_id}:{domain.value}:{contract.security_id}:"
                        f"{_fingerprint(payload, received_at)}"
                    ),
                    source_id=source_id,
                    domain=domain,
                    subject=contract.subject,
                    observed_at=received_at,
                    received_at=received_at,
                    payload=payload,
                    trust_score=1.0,
                )
            )
    return tuple(events)


def _fingerprint(payload: dict[str, Any], observed_at: datetime) -> str:
    canonical = json.dumps(
        {"payload": payload, "observed_at": observed_at.isoformat()},
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:24]
