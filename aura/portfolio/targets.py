from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aura.risk.quantity import QuantityRule


class TargetExposureIntent(BaseModel):
    """Broker-neutral desired portfolio exposure; never an execution permission."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    target_equity_fraction: Decimal = Field(ge=Decimal(-1), le=Decimal(1))
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=2000)


class PortfolioTargetSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    intents: tuple[TargetExposureIntent, ...]
    max_gross_target_fraction: Decimal = Field(default=Decimal("1.0"), gt=0)

    @model_validator(mode="after")
    def validate_targets(self) -> PortfolioTargetSet:
        symbols = [item.symbol for item in self.intents]
        if len(symbols) != len(set(symbols)):
            raise ValueError("portfolio target symbols must be unique")
        gross = sum(
            (abs(item.target_equity_fraction) for item in self.intents),
            Decimal(0),
        )
        if gross > self.max_gross_target_fraction:
            raise ValueError(
                f"gross target fraction {gross} exceeds {self.max_gross_target_fraction}"
            )
        return self


@dataclass(slots=True, frozen=True)
class TargetQuantityDecision:
    symbol: str
    target_fraction: Decimal
    target_notional: Decimal
    target_quantity: Decimal
    current_quantity: Decimal
    delta_quantity: Decimal
    reference_price: Decimal
    notional_multiplier: Decimal
    confidence: float


class PortfolioTargetPlanner:
    """Translate PM-style target exposures into broker-neutral quantity deltas.

    The output still enters AURA's existing RiskEngine before any order exists.
    This planner cannot widen risk limits, submit orders or infer broker margin.
    """

    def plan(
        self,
        targets: PortfolioTargetSet,
        *,
        equity: Decimal,
        prices: dict[str, Decimal],
        current_quantities: dict[str, Decimal],
        notional_multipliers: dict[str, Decimal],
        quantity_rules: dict[str, QuantityRule],
    ) -> tuple[TargetQuantityDecision, ...]:
        if equity <= 0:
            raise ValueError("equity must be positive")
        decisions: list[TargetQuantityDecision] = []
        for intent in targets.intents:
            price = prices.get(intent.symbol)
            if price is None or price <= 0:
                raise ValueError(f"missing positive reference price for {intent.symbol}")
            multiplier = notional_multipliers.get(intent.symbol, Decimal(1))
            if multiplier <= 0:
                raise ValueError(f"invalid notional multiplier for {intent.symbol}")
            rule = quantity_rules.get(intent.symbol)
            if rule is None:
                raise ValueError(f"missing quantity rule for {intent.symbol}")
            target_notional = equity * intent.target_equity_fraction
            raw_quantity = abs(target_notional) / (price * multiplier)
            target_abs = _round_down_to_step(raw_quantity, rule)
            target_quantity = (
                target_abs
                if intent.target_equity_fraction >= 0
                else -target_abs
            )
            current = current_quantities.get(intent.symbol, Decimal(0))
            decisions.append(
                TargetQuantityDecision(
                    symbol=intent.symbol,
                    target_fraction=intent.target_equity_fraction,
                    target_notional=target_notional,
                    target_quantity=target_quantity,
                    current_quantity=current,
                    delta_quantity=target_quantity - current,
                    reference_price=price,
                    notional_multiplier=multiplier,
                    confidence=intent.confidence,
                )
            )
        return tuple(decisions)


def _round_down_to_step(quantity: Decimal, rule: QuantityRule) -> Decimal:
    if quantity < rule.minimum:
        return Decimal(0)
    steps = ((quantity - rule.minimum) / rule.step).to_integral_value(
        rounding=ROUND_FLOOR
    )
    value = rule.minimum + steps * rule.step
    if rule.maximum is not None:
        value = min(value, rule.maximum)
    return value
