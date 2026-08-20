from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.runtime.free_public_ai_council import FreePublicAICouncilCounters
from aura.runtime.observable_public_council import ObservableFreePublicAICouncilRuntime
from aura.runtime.scanner import MarketScanResult, ScanCandidate


def _scan() -> tuple[AgentContext, MarketScanResult]:
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="BTC-USD",
        venue="COINBASE_PUBLIC",
        timeframe="1s",
        open_time=now - timedelta(seconds=1),
        close_time=now,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal("100.5"),
        volume=Decimal(10),
        closed=True,
    )
    context = AgentContext(
        correlation_id="observable:test",
        symbol="BTC-USD",
        decision_timeframe="1s",
        candles=(candle,),
        created_at=now,
    )
    memo = CEODecisionMemo(
        correlation_id=context.correlation_id,
        intent=SignalIntent.LONG,
        confidence=0.8,
        supporting_agents=("technical",),
        opposing_agents=(),
        abstaining_agents=(),
        risk_flags=(),
        rationale="test",
        quorum_met=True,
        generated_at=now,
    )
    round_result = AgentRound(
        correlation_id=context.correlation_id,
        evidence=(),
        failures=(),
        started_at=now,
        completed_at=now,
    )
    candidate = ScanCandidate(
        context=context,
        round=round_result,
        memo=memo,
        data_quality=None,
    )
    return context, MarketScanResult(candidates=(candidate,))


def _runtime(scan: MarketScanResult, observer):
    runtime = ObservableFreePublicAICouncilRuntime.__new__(
        ObservableFreePublicAICouncilRuntime
    )
    runtime._decision_semaphore = asyncio.Semaphore(1)

    async def enrich(context):
        return context

    runtime._enrich_context = enrich
    runtime.scanner = SimpleNamespace(scan=_async_scan(scan))
    runtime.recorder = SimpleNamespace(register_scan=lambda _result: None)
    runtime.opportunity_auditor = SimpleNamespace(register_scan=lambda _result: None)
    runtime.counters = FreePublicAICouncilCounters()
    runtime.scan_observer = observer
    runtime.status_events = []
    runtime._write_status = lambda candidate, last_error=None: runtime.status_events.append(
        (candidate, last_error)
    )
    return runtime


def _async_scan(result):
    async def scan(_contexts):
        return result

    return scan


@pytest.mark.asyncio
async def test_observer_receives_completed_governed_scan() -> None:
    context, scan = _scan()
    observed = []
    runtime = _runtime(scan, observed.append)

    await runtime._analyze(context)

    assert observed == [scan]
    assert runtime.counters.ai_decisions_completed == 1
    assert runtime.counters.actionable_decisions == 1
    assert runtime.status_events[-1][1] is None


@pytest.mark.asyncio
async def test_observer_failure_is_isolated_and_visible() -> None:
    context, scan = _scan()

    def fail(_result):
        raise RuntimeError("dashboard unavailable")

    runtime = _runtime(scan, fail)
    await runtime._analyze(context)

    assert runtime.counters.ai_decisions_completed == 1
    assert runtime.status_events
    assert "operator observer RuntimeError: dashboard unavailable" in runtime.status_events[-1][1]
    assert not hasattr(runtime, "submit_order")
