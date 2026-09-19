from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

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
from aura.domain.models import NormalizedCandle, PortfolioSnapshot, SignalIntent
from aura.risk.engine import RiskEngine, RiskLimits
from aura.runtime.allocation import PortfolioRiskCoordinator
from aura.runtime.scanner import MultiMarketIntelligenceScanner
from aura.strategy.ema import EmaCrossStrategy


class BarrierContextAgent(SpecialistAgent):
    def __init__(
        self,
        *,
        agent_id: str,
        role: AgentRole,
        started: list[str],
        gate: asyncio.Event,
        expected_calls: int,
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self.started = started
        self.gate = gate
        self.expected_calls = expected_calls

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        self.started.append(f"{self.agent_id}:{context.symbol}")
        if len(self.started) == self.expected_calls:
            self.gate.set()
        await self.gate.wait()
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=SignalIntent.LONG,
            confidence=0.8,
            thesis=f"{self.role.value} confirms {context.symbol}",
            sources=(
                EvidenceSource(
                    source_id=f"market:{context.symbol}",
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=context.candles[-1].close_time,
                    trust_score=1.0,
                ),
            ),
            generated_at=context.created_at,
        )


def _context(symbol: str) -> AgentContext:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol=symbol,
        venue="TEST",
        timeframe="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(100),
        closed=True,
    )
    return AgentContext(
        correlation_id=f"scan:{symbol}",
        symbol=symbol,
        decision_timeframe="5m",
        candles=(candle,),
        created_at=candle.close_time,
    )


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=Decimal(10000),
        equity=Decimal(10000),
        gross_exposure=Decimal(0),
        net_exposure=Decimal(0),
        realized_pnl=Decimal(0),
        unrealized_pnl=Decimal(0),
        peak_equity=Decimal(10000),
        drawdown_pct=Decimal(0),
    )


@pytest.mark.asyncio
async def test_markets_scan_concurrently_then_share_one_reserved_risk_budget() -> None:
    started: list[str] = []
    gate = asyncio.Event()
    agents = [
        BarrierContextAgent(
            agent_id="htf",
            role=AgentRole.HTF_BIAS,
            started=started,
            gate=gate,
            expected_calls=9,
        ),
        BarrierContextAgent(
            agent_id="technical",
            role=AgentRole.TECHNICAL,
            started=started,
            gate=gate,
            expected_calls=9,
        ),
        BarrierContextAgent(
            agent_id="volume",
            role=AgentRole.VOLUME_VWAP,
            started=started,
            gate=gate,
            expected_calls=9,
        ),
    ]
    scanner = MultiMarketIntelligenceScanner(
        orchestrator=MultiAgentOrchestrator(agents, timeout_seconds=1),
        ceo=CEOAggregator(min_agents=3, min_distinct_roles=3),
        data_quality_gate=CandleQualityGate(
            DataQualityPolicy(
                expected_interval=timedelta(minutes=5),
                max_staleness=timedelta(minutes=1),
            )
        ),
        max_concurrent_contexts=3,
    )
    scan = await scanner.scan([_context("X"), _context("Y"), _context("Z")])

    assert len(started) == 9
    assert len(scan.opportunities) == 3
    assert [candidate.context.symbol for candidate in scan.opportunities] == ["X", "Y", "Z"]

    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(10),
        )
    )
    coordinator = PortfolioRiskCoordinator(
        DecisionPipeline(EmaCrossStrategy(fast=2, slow=3), risk)
    )
    allocation = coordinator.allocate(
        scan,
        portfolio=_portfolio(),
        day_start_equity=Decimal(10000),
        default_requested_quantity=Decimal(8),
    )

    assert len(allocation.allocations) == 3
    assert len(allocation.approved) == 2
    first, second, third = allocation.allocations
    assert first.decision is not None and first.decision.order is not None
    assert second.decision is not None and second.decision.order is not None
    assert third.decision is not None and third.decision.order is None
    assert first.decision.order.quantity == Decimal(8)
    assert second.decision.order.quantity == Decimal(2)
    assert allocation.reserved_gross_notional == Decimal(1000)
