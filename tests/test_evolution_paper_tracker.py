from decimal import Decimal
from pathlib import Path

import pytest

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


def test_paper_trade_journal_recovers_and_retries_idempotently(tmp_path: Path) -> None:
    genome = StrategyGenome(family="x", parameters={"p": 1})
    journal = tmp_path / "paper_evidence.jsonl"
    trade = PaperTradeOutcome(
        trade_id="paper-order-1",
        symbol="XAUUSD",
        gross_pnl=Decimal(100),
        fees=Decimal(2),
        slippage_cost=Decimal(3),
    )
    tracker = PaperGenomePerformanceTracker(
        starting_equity=Decimal(10000),
        journal_path=journal,
    )

    assert tracker.record_trade(genome, trade) is True
    assert tracker.record_trade(genome, trade) is False
    assert tracker.trade_count(genome) == 1

    restored = PaperGenomePerformanceTracker(
        starting_equity=Decimal(10000),
        journal_path=journal,
    )
    assert restored.recovered_events == 1
    assert restored.trade_count(genome) == 1
    assert restored.performance_for(genome) == tracker.performance_for(genome)
    assert restored.record_trade(genome, trade) is False

    conflicting = trade.model_copy(update={"gross_pnl": Decimal(-100)})
    with pytest.raises(ValueError, match="trade_id collision"):
        restored.record_trade(genome, conflicting)


def test_paper_incidents_are_durable_and_idempotent(tmp_path: Path) -> None:
    genome = StrategyGenome(family="x", parameters={"p": 1})
    journal = tmp_path / "paper_incidents.jsonl"
    tracker = PaperGenomePerformanceTracker(
        starting_equity=Decimal(10000),
        journal_path=journal,
    )

    assert tracker.record_reconciliation_incident(
        genome,
        incident_id="reconcile-1",
    )
    assert not tracker.record_reconciliation_incident(
        genome,
        incident_id="reconcile-1",
    )
    assert tracker.record_operational_incident(
        genome,
        incident_id="feed-gap-1",
    )

    restored = PaperGenomePerformanceTracker(
        starting_equity=Decimal(10000),
        journal_path=journal,
    )
    assert restored.reconciliation_incidents_for(genome) == 1
    assert restored.operational_incidents_for(genome) == 1
    assert restored.recovered_events == 2


def test_paper_journal_write_precedes_in_memory_trade_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    genome = StrategyGenome(family="x", parameters={"p": 1})
    journal = tmp_path / "paper_crash.jsonl"
    tracker = PaperGenomePerformanceTracker(
        starting_equity=Decimal(10000),
        journal_path=journal,
    )
    trade = PaperTradeOutcome(
        trade_id="paper-order-crash",
        symbol="XAUUSD",
        gross_pnl=Decimal(50),
    )

    def fail_after_append(_event):
        raise RuntimeError("simulated paper tracker crash")

    monkeypatch.setattr(tracker, "_apply_trade_event", fail_after_append)
    with pytest.raises(RuntimeError, match="simulated paper tracker crash"):
        tracker.record_trade(genome, trade)
    assert tracker.trade_count(genome) == 0

    restored = PaperGenomePerformanceTracker(
        starting_equity=Decimal(10000),
        journal_path=journal,
    )
    assert restored.trade_count(genome) == 1


def test_paper_journal_rejects_equity_drift_and_corruption(tmp_path: Path) -> None:
    journal = tmp_path / "paper_invalid.jsonl"
    PaperGenomePerformanceTracker(
        starting_equity=Decimal(10000),
        journal_path=journal,
    )
    with pytest.raises(RuntimeError, match="starting_equity changed"):
        PaperGenomePerformanceTracker(
            starting_equity=Decimal(20000),
            journal_path=journal,
        )

    raw = journal.read_text(encoding="utf-8")
    journal.write_text(raw.replace("10000", "99999", 1), encoding="utf-8")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        PaperGenomePerformanceTracker(
            starting_equity=Decimal(10000),
            journal_path=journal,
        )
