from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from aura.markets.universe import OptionType


class OptionGreeks(BaseModel):
    model_config = ConfigDict(frozen=True)

    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0


class OptionContractObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    underlying: str = Field(min_length=1)
    expiry: datetime
    strike: Decimal = Field(gt=0)
    option_type: OptionType
    spot: Decimal = Field(gt=0)
    last_price: Decimal = Field(ge=0)
    bid: Decimal = Field(default=Decimal(0), ge=0)
    ask: Decimal = Field(default=Decimal(0), ge=0)
    open_interest: Decimal = Field(default=Decimal(0), ge=0)
    volume: Decimal = Field(default=Decimal(0), ge=0)
    implied_volatility: float = Field(default=0.0, ge=0)
    greeks: OptionGreeks = Field(default_factory=OptionGreeks)
    observed_at: datetime


@dataclass(slots=True, frozen=True)
class WeightedGreeks:
    delta: float
    gamma: float
    theta: float
    vega: float
    open_interest_weight: float


@dataclass(slots=True, frozen=True)
class OptionChainIntelligence:
    underlying: str
    expiry: datetime
    observed_at: datetime
    spot: Decimal
    contracts: int
    liquid_contracts: int
    put_call_oi_ratio: float | None
    put_call_volume_ratio: float | None
    atm_strike: Decimal | None
    atm_iv: float | None
    put_minus_call_atm_iv: float | None
    expected_move_1sigma: Decimal | None
    weighted_greeks: WeightedGreeks
    unsigned_gamma_oi_proxy: float
    median_relative_spread_bps: float | None


@dataclass(slots=True, frozen=True)
class OptionLiquidityPolicy:
    max_relative_spread_bps: float = 300.0
    min_open_interest: Decimal = Decimal(1)
    min_volume: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if self.max_relative_spread_bps <= 0:
            raise ValueError("max_relative_spread_bps must be positive")
        if self.min_open_interest < 0 or self.min_volume < 0:
            raise ValueError("liquidity floors cannot be negative")


class OptionChainAggregator:
    """Aggregate point-in-time option contracts without inventing dealer signs.

    Gamma is exposed as an *unsigned OI-weighted proxy*. It is not called dealer
    GEX because public OI alone does not reveal whether dealers are long/short the
    contracts. This keeps AURA's derivatives evidence explicit and defensible.
    """

    def __init__(self, policy: OptionLiquidityPolicy | None = None) -> None:
        self.policy = policy or OptionLiquidityPolicy()

    def aggregate(
        self,
        observations: tuple[OptionContractObservation, ...] | list[OptionContractObservation],
        *,
        as_of: datetime,
    ) -> OptionChainIntelligence:
        if not observations:
            raise ValueError("option chain cannot be empty")
        first = observations[0]
        underlying = first.underlying
        expiry = first.expiry
        if any(item.underlying != underlying or item.expiry != expiry for item in observations):
            raise ValueError("aggregate one underlying/expiry at a time")
        visible = [item for item in observations if item.observed_at <= as_of]
        if not visible:
            raise ValueError("no point-in-time option observations are visible")
        latest_time = max(item.observed_at for item in visible)
        latest = [item for item in visible if item.observed_at == latest_time]
        spot = _median_decimal([item.spot for item in latest])
        liquid = [item for item in latest if self._is_liquid(item)]
        analytical = liquid or latest

        calls = [item for item in analytical if item.option_type == OptionType.CALL]
        puts = [item for item in analytical if item.option_type == OptionType.PUT]
        call_oi = sum((item.open_interest for item in calls), Decimal(0))
        put_oi = sum((item.open_interest for item in puts), Decimal(0))
        call_volume = sum((item.volume for item in calls), Decimal(0))
        put_volume = sum((item.volume for item in puts), Decimal(0))

        strikes = sorted({item.strike for item in analytical})
        atm_strike = min(strikes, key=lambda strike: abs(strike - spot)) if strikes else None
        atm_calls = [
            item
            for item in calls
            if atm_strike is not None and item.strike == atm_strike and item.implied_volatility > 0
        ]
        atm_puts = [
            item
            for item in puts
            if atm_strike is not None and item.strike == atm_strike and item.implied_volatility > 0
        ]
        atm_iv_values = [item.implied_volatility for item in (*atm_calls, *atm_puts)]
        atm_iv = sum(atm_iv_values) / len(atm_iv_values) if atm_iv_values else None
        call_iv = _mean([item.implied_volatility for item in atm_calls])
        put_iv = _mean([item.implied_volatility for item in atm_puts])
        skew = put_iv - call_iv if put_iv is not None and call_iv is not None else None

        total_oi = float(sum((item.open_interest for item in analytical), Decimal(0)))
        if total_oi > 0:
            weighted_delta = sum(float(item.open_interest) * item.greeks.delta for item in analytical) / total_oi
            weighted_gamma = sum(float(item.open_interest) * item.greeks.gamma for item in analytical) / total_oi
            weighted_theta = sum(float(item.open_interest) * item.greeks.theta for item in analytical) / total_oi
            weighted_vega = sum(float(item.open_interest) * item.greeks.vega for item in analytical) / total_oi
        else:
            weighted_delta = weighted_gamma = weighted_theta = weighted_vega = 0.0

        unsigned_gamma_proxy = sum(
            abs(item.greeks.gamma) * float(item.open_interest) * float(spot) ** 2
            for item in analytical
        )
        spreads = [
            spread
            for item in analytical
            if (spread := _relative_spread_bps(item)) is not None
        ]

        return OptionChainIntelligence(
            underlying=underlying,
            expiry=expiry,
            observed_at=latest_time,
            spot=spot,
            contracts=len(latest),
            liquid_contracts=len(liquid),
            put_call_oi_ratio=_ratio(put_oi, call_oi),
            put_call_volume_ratio=_ratio(put_volume, call_volume),
            atm_strike=atm_strike,
            atm_iv=atm_iv,
            put_minus_call_atm_iv=skew,
            expected_move_1sigma=_expected_move(
                spot,
                atm_iv,
                as_of=as_of,
                expiry=expiry,
            ),
            weighted_greeks=WeightedGreeks(
                delta=weighted_delta,
                gamma=weighted_gamma,
                theta=weighted_theta,
                vega=weighted_vega,
                open_interest_weight=total_oi,
            ),
            unsigned_gamma_oi_proxy=unsigned_gamma_proxy,
            median_relative_spread_bps=_median_float(spreads),
        )

    def _is_liquid(self, item: OptionContractObservation) -> bool:
        spread = _relative_spread_bps(item)
        return (
            item.open_interest >= self.policy.min_open_interest
            and item.volume >= self.policy.min_volume
            and spread is not None
            and spread <= self.policy.max_relative_spread_bps
        )


def _relative_spread_bps(item: OptionContractObservation) -> float | None:
    if item.bid <= 0 or item.ask <= 0 or item.ask < item.bid:
        return None
    midpoint = (item.bid + item.ask) / Decimal(2)
    if midpoint <= 0:
        return None
    return float((item.ask - item.bid) / midpoint * Decimal(10000))


def _ratio(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator / denominator)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median_float(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _median_decimal(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _expected_move(
    spot: Decimal,
    atm_iv: float | None,
    *,
    as_of: datetime,
    expiry: datetime,
) -> Decimal | None:
    if atm_iv is None or atm_iv <= 0 or expiry <= as_of:
        return None
    years = (expiry - as_of).total_seconds() / (365.25 * 24 * 3600)
    if years <= 0:
        return None
    iv_decimal = atm_iv / 100.0 if atm_iv > 3.0 else atm_iv
    return spot * Decimal(str(iv_decimal * math.sqrt(years)))
