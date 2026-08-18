from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from pydantic import BaseModel, ConfigDict, Field


class QuantityRule(BaseModel):
    """Broker/exchange quantity grid used after economic risk sizing."""

    model_config = ConfigDict(frozen=True)

    minimum: Decimal = Field(gt=0)
    step: Decimal = Field(gt=0)
    maximum: Decimal | None = Field(default=None, gt=0)

    def normalize_down(self, quantity: Decimal) -> Decimal:
        if quantity < self.minimum:
            return Decimal(0)
        capped = min(quantity, self.maximum) if self.maximum is not None else quantity
        units = ((capped - self.minimum) / self.step).to_integral_value(
            rounding=ROUND_FLOOR
        )
        normalized = self.minimum + units * self.step
        if self.maximum is not None:
            normalized = min(normalized, self.maximum)
        return max(Decimal(0), normalized)
