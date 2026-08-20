from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.agents.risk_policy import AgentPolicyDecision
from aura.domain.models import NormalizedCandle, PortfolioSnapshot, SignalIntent
from aura.interface.operator_read_model import OperatorReadModel, ReadDomain
from aura.interface.runtime_bridge import OperatorRuntimeBridge, RuntimeBridgeFreshness
from aura.risk.engine import RiskEngine, RiskLimits
from aura.runtime.allocation import PortfolioAllocationResult
from aura.runtime.multi_market_paper import MultiMarketPaperStep
from aura.runtime.scanner import MarketScanResult, ScanCandidate


def _candidate(now: datetime) -> ScanCandidate:
    start = now - timedelta(minutes=220)
    candles: list[NormalizedCandle] = []
    previous = Decimal(100)
    for index in range(220):
        close = previous + Decimal("0.25")
        opened = start + timedelta(minutes=index)
        candles.append(
            NormalizedCandle(
                symbol="BTC/USD",
                venue="PUBLIC_TEST",
                timeframe="1m",
                open_time=opened,
                close_time=opened + timedelta(minutes=1),
                open=previous,
                high=close + Decimal(1),
                low=previous - Decimal(1),
                close=close,
                volume=Decimal(100 + index),
                closed=True,
            )
        )
        previous = close
    context = AgentContext(
        correlation_id="bridge:btc",
        symbol="BTC/USD",
        decision_timeframe="1m",
        candles=tuple(candles),
        created_at=now,
        metadata={"runtime": "test-public"},
    )
    memo = CEODecisionMemo(
        correlation_id=context.correlation_id,
        intent=SignalIntent.LONG,
        confidence=0.82,
        supporting_agents=("technical", "volume"),
        opposing_agents=(),
        abstaining_agents=("macro",),
        risk_flags=(),
        rationale="governed test opportunity",
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
    return ScanCandidate(
        context=context,
        round=round_result,
        memo=memo,
        data_quality=None,
        agent_policy=AgentPolicyDecision(allowed=True, reasons=()),
        deliberation=None,
    )


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=Decimal(100000),
        equity=Decimal(101000),
        gross_exposure=Decimal(10000),
        net_exposure=Decimal(10000),
        realized_pnl=Decimal(500),
        unrealized_pnl=Decimal(500),
        peak_equity=Decimal(102000),
        drawdown_pct=Decimal("0.9803921569"),
        position_values={"BTC/USD": Decimal(10000)},
    )


def test_scan_bridge_populates_governed_dashboard_domains() -> None:
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    store = OperatorReadModel()
    bridge = OperatorRuntimeBridge(store)
    scan = MarketScanResult(candidates=(_candidate(now),))

    bridge.publish_scan(
        scan,
        source="public-runtime",
        received_at=now,
        runtime_metadata={"provider": "public-test"},
    )

    opportunities = store.get(ReadDomain.OPPORTUNITIES, as_of=now)
    agents = store.get(ReadDomain.AGENTS, as_of=now)
    data = store.get(ReadDomain.DATA, as_of=now)
    system = store.get(ReadDomain.SYSTEM, as_of=now)

    assert opportunities.available is True
    assert opportunities.payload is not None
    assert opportunities.payload["actionable_count"] == 1
    assert opportunities.payload["items"][0]["symbol"] == "BTC/USD"
    assert agents.payload is not None
    assert agents.payload["candidates"][0]["ceo"]["intent"] == "LONG"
    assert data.payload is not None
    assert data.payload["series"][0]["venue"] == "PUBLIC_TEST"
    assert system.payload is not None
    assert system.payload["broker_order_authority"] is False
    assert system.payload["live_money_enabled"] is False
    assert system.payload["runtime"] == {"provider": "public-test"}


def test_paper_step_bridge_exposes_portfolio_risk_and_paper_broker_only() -> None:
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    scan = MarketScanResult(candidates=(_candidate(now),))
    step = MultiMarketPaperStep(
        close_time_iso=now.isoformat(),
        fills=(),
        scan=scan,
        allocation=PortfolioAllocationResult(
            allocations=(),
            reserved_gross_notional=Decimal(0),
        ),
        submitted_orders=(),
        portfolio=_portfolio(),
    )
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(2),
            max_gross_exposure_pct=Decimal(50),
            max_symbol_exposure_pct=Decimal(20),
            max_drawdown_pct=Decimal(6),
            max_daily_loss_pct=Decimal(3),
        )
    )
    store = OperatorReadModel()
    bridge = OperatorRuntimeBridge(store)

    bridge.publish_paper_step(
        step,
        risk_engine=risk,
        day_start_equity=Decimal(100000),
        received_at=now,
    )

    portfolio = store.get(ReadDomain.PORTFOLIO, as_of=now)
    risk_view = store.get(ReadDomain.RISK, as_of=now)
    broker = store.get(ReadDomain.BROKERS, as_of=now)

    assert portfolio.payload is not None
    assert portfolio.payload["equity"] == "101000"
    assert portfolio.payload["position_values"] == {"BTC/USD": "10000"}
    assert risk_view.payload is not None
    assert risk_view.payload["authority"] == "INDEPENDENT_RISK_ENGINE"
    assert risk_view.payload["limits"]["max_drawdown_pct"] == "6"
    assert risk_view.payload["live_money_enabled"] is False
    assert broker.payload is not None
    assert broker.payload["execution_mode"] == "PAPER"
    assert broker.payload["live_money_enabled"] is False
    assert not hasattr(bridge, "submit_order")
    assert not hasattr(bridge, "cancel_order")


def test_bridge_freshness_policy_is_enforced_by_read_model() -> None:
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    store = OperatorReadModel()
    bridge = OperatorRuntimeBridge(
        store,
        freshness=RuntimeBridgeFreshness(opportunities=timedelta(seconds=5)),
    )
    bridge.publish_scan(
        MarketScanResult(candidates=(_candidate(now),)),
        source="public-runtime",
        received_at=now,
    )

    stale = store.get(ReadDomain.OPPORTUNITIES, as_of=now + timedelta(seconds=6))
    assert stale.available is False
    assert stale.stale is True
    assert stale.payload is None


def test_empty_scan_requires_explicit_observation_time() -> None:
    store = OperatorReadModel()
    bridge = OperatorRuntimeBridge(store)
    try:
        bridge.publish_scan(MarketScanResult(candidates=()), source="empty")
    except ValueError as exc:
        assert "observed_at" in str(exc)
    else:
        raise AssertionError("empty scan without observed_at must fail closed")
