from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aura.agents.audit import AgentAuditJournal
from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.orchestrator import CEOAggregator, MultiAgentOrchestrator
from aura.core.pipeline import DecisionPipeline
from aura.data.quality import CandleQualityGate, DataQualityPolicy
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.execution.paper import PaperBroker
from aura.persistence.recovery import FinancialEventJournal
from aura.persistence.wal import JsonlWriteAheadLog
from aura.portfolio.ledger import PortfolioLedger
from aura.risk.engine import RiskEngine, RiskLimits
from aura.runtime.allocation import PortfolioRiskCoordinator
from aura.runtime.multi_market_paper import MultiMarketPaperCoordinator
from aura.runtime.scanner import MultiMarketIntelligenceScanner
from aura.strategy.ema import EmaCrossStrategy


class AlwaysLongAgent(SpecialistAgent):
    def __init__(self, agent_id: str, role: AgentRole) -> None:
        self.agent_id = agent_id
        self.role = role

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=SignalIntent.LONG,
            confidence=0.8,
            thesis=f"{self.role.value} confirms long",
            sources=(
                EvidenceSource(
                    source_id=f"market:{context.symbol}:{self.role.value}",
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=context.candles[-1].close_time,
                    trust_score=1.0,
                ),
            ),
            generated_at=context.created_at,
        )


def _candle(symbol: str, minute: int, open_price: str, close_price: str) -> NormalizedCandle:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    open_value = Decimal(open_price)
    close_value = Decimal(close_price)
    return NormalizedCandle(
        symbol=symbol,
        venue="PAPER",
        timeframe="1m",
        open_time=start,
        close_time=start + timedelta(minutes=1),
        open=open_value,
        high=max(open_value, close_value),
        low=min(open_value, close_value),
        close=close_value,
        volume=Decimal(100),
        closed=True,
    )


@pytest.mark.asyncio
async def test_multi_market_paper_loop_shares_capital_and_reconciles(tmp_path: Path) -> None:
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(10),
        )
    )
    agents = [
        AlwaysLongAgent("htf", AgentRole.HTF_BIAS),
        AlwaysLongAgent("technical", AgentRole.TECHNICAL),
        AlwaysLongAgent("volume", AgentRole.VOLUME_VWAP),
    ]
    scanner = MultiMarketIntelligenceScanner(
        orchestrator=MultiAgentOrchestrator(agents, timeout_seconds=1),
        ceo=CEOAggregator(min_agents=3, min_distinct_roles=3),
        data_quality_gate=CandleQualityGate(
            DataQualityPolicy(
                expected_interval=timedelta(minutes=1),
                max_staleness=timedelta(days=36500),
            )
        ),
        max_concurrent_contexts=2,
    )
    allocator = PortfolioRiskCoordinator(
        DecisionPipeline(EmaCrossStrategy(fast=2, slow=3), risk)
    )
    broker = PaperBroker()
    ledger = PortfolioLedger(Decimal(10000))
    financial_wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    audit_wal = JsonlWriteAheadLog(tmp_path / "agent-audit.wal", fsync=False)
    runtime = MultiMarketPaperCoordinator(
        scanner=scanner,
        allocator=allocator,
        broker=broker,
        ledger=ledger,
        financial_journal=FinancialEventJournal(financial_wal),
        agent_audit_journal=AgentAuditJournal(audit_wal),
        risk_engine=risk,
        starting_cash=Decimal(10000),
        default_requested_quantity=Decimal(8),
    )
    await runtime.start()

    first = await runtime.on_batch(
        [_candle("Y", 0, "100", "100"), _candle("X", 0, "100", "100")]
    )
    assert first.fills == ()
    assert len(first.submitted_orders) == 2
    quantities = {item.order.symbol: item.order.quantity for item in first.submitted_orders}
    assert quantities == {"X": Decimal(8), "Y": Decimal(2)}
    assert ledger.positions == {}
    assert len(audit_wal.read_all()) == 2

    second = await runtime.on_batch(
        [_candle("X", 1, "101", "102"), _candle("Y", 1, "101", "102")]
    )
    assert len(second.fills) == 2
    assert ledger.positions["X"].quantity == Decimal(8)
    assert ledger.positions["Y"].quantity == Decimal(2)
    assert second.portfolio.equity == Decimal(10010)
    assert second.submitted_orders == ()
    assert len(audit_wal.read_all()) == 4

    report = runtime.reconcile()
    assert report.safe_for_new_risk
    assert not risk.kill_switch

    await runtime.stop()
