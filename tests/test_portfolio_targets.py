from decimal import Decimal

import pytest

from aura.portfolio.targets import (
    PortfolioTargetPlanner,
    PortfolioTargetSet,
    TargetExposureIntent,
)
from aura.risk.quantity import QuantityRule


def test_target_planner_translates_exposure_to_quantity_delta() -> None:
    targets = PortfolioTargetSet(
        intents=(
            TargetExposureIntent(
                symbol="XAUUSD",
                target_equity_fraction=Decimal("0.10"),
                confidence=0.8,
            ),
        )
    )
    decision = PortfolioTargetPlanner().plan(
        targets,
        equity=Decimal(10000),
        prices={"XAUUSD": Decimal(2500)},
        current_quantities={"XAUUSD": Decimal("0.1")},
        notional_multipliers={"XAUUSD": Decimal(1)},
        quantity_rules={
            "XAUUSD": QuantityRule(
                minimum=Decimal("0.01"),
                step=Decimal("0.01"),
                maximum=Decimal(10),
            )
        },
    )[0]
    assert decision.target_quantity == Decimal("0.40")
    assert decision.delta_quantity == Decimal("0.30")


def test_target_set_rejects_unbounded_gross_exposure() -> None:
    with pytest.raises(ValueError, match="gross target fraction"):
        PortfolioTargetSet(
            intents=(
                TargetExposureIntent(
                    symbol="A",
                    target_equity_fraction=Decimal("0.7"),
                    confidence=0.8,
                ),
                TargetExposureIntent(
                    symbol="B",
                    target_equity_fraction=Decimal("0.6"),
                    confidence=0.8,
                ),
            ),
            max_gross_target_fraction=Decimal(1),
        )
