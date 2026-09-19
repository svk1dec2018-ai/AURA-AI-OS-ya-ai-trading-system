from datetime import UTC, datetime
from decimal import Decimal

from aura.research.lifecycle import EvidenceKind
from aura.research.paper_evidence import (
    PaperTradeOutcome,
    PaperValidationThresholds,
    build_paper_validation_evidence,
    evaluate_paper_performance,
    summarize_paper_trades,
)


def test_profitable_stable_paper_run_generates_passed_governance_evidence() -> None:
    trades = [
        PaperTradeOutcome(
            trade_id=f"t-{index}",
            symbol="XAUUSD",
            gross_pnl=Decimal(15 if index % 4 else -8),
            fees=Decimal(1),
            slippage_cost=Decimal(1),
        )
        for index in range(120)
    ]
    summary = summarize_paper_trades(trades, starting_equity=Decimal(10000))
    thresholds = PaperValidationThresholds(
        min_trades=100,
        min_expectancy_per_trade=Decimal("0.5"),
        min_profit_factor=1.2,
        max_drawdown_pct=10,
    )
    decision = evaluate_paper_performance(summary, thresholds=thresholds)
    evidence = build_paper_validation_evidence(
        summary,
        thresholds=thresholds,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert decision.passed
    assert evidence.kind == EvidenceKind.PAPER_TRADING
    assert evidence.passed
    assert len(evidence.artifact_hash) == 64


def test_reconciliation_incident_blocks_paper_promotion_even_when_pnl_is_positive() -> None:
    trades = [
        PaperTradeOutcome(
            trade_id=f"t-{index}",
            symbol="NIFTY",
            gross_pnl=Decimal(10),
        )
        for index in range(100)
    ]
    summary = summarize_paper_trades(
        trades,
        starting_equity=Decimal(10000),
        reconciliation_incidents=1,
    )
    decision = evaluate_paper_performance(
        summary,
        thresholds=PaperValidationThresholds(min_trades=100),
    )
    assert not decision.passed
    assert any("reconciliation" in reason for reason in decision.reasons)


def test_too_few_paper_trades_cannot_pass() -> None:
    summary = summarize_paper_trades(
        [
            PaperTradeOutcome(
                trade_id="one",
                symbol="BTCUSDT",
                gross_pnl=Decimal(100),
            )
        ],
        starting_equity=Decimal(10000),
    )
    decision = evaluate_paper_performance(
        summary,
        thresholds=PaperValidationThresholds(min_trades=30),
    )
    assert not decision.passed
    assert "paper trades 1 < required 30" in decision.reasons[0]
