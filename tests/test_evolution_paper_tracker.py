from decimal import Decimal

from aura.evolution.core import StrategyGenome
from aura.evolution.paper_tracker import PaperGenomePerformanceTracker
from aura.research.paper_evidence import PaperTradeOutcome


def test_paper_tracker_uses_only_measured_genome_outcomes() -> None:
    first = StrategyGenome(family="x", parameters={"p": 1})
    second = StrategyGenome(family="x", parameters={"p": 2})
    tracker = PaperGenomePerformanceTracker(starting_equity=Decimal(10000))
    assert tracker.performance_for(first) is None
    tracker.record_trade(
        first,
        PaperTradeOutcome(
            trade_id="t1",
            symbol="XAUUSD",
            gross_pnl=Decimal(100),
            fees=Decimal(2),
            slippage_cost=Decimal(3),
        ),
    )
    tracker.record_trade(
        first,
        PaperTradeOutcome(
            trade_id="t2",
            symbol="XAUUSD",
            gross_pnl=Decimal(-40),
            fees=Decimal(1),
            slippage_cost=Decimal(1),
        ),
    )
    performance = tracker.performance_for(first)
    assert performance is not None
    assert performance.trades == 2
    assert performance.net_return_pct == 0.53
    assert tracker.performance_for(second) is None
