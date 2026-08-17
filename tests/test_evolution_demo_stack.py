from __future__ import annotations

from collections import namedtuple
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from aura.data.mt5_demo import (
    MT5DemoClosedCandleSource,
    MT5DemoCredentials,
    OfficialMT5Gateway,
)
from aura.domain.models import OrderRequest, Side
from aura.evolution.core import (
    CandidateEvaluation,
    EvolutionConfig,
    EvolutionJournal,
    FitnessPolicy,
    GeneKind,
    GeneSpec,
    PerformanceSlice,
    PopulationEvolution,
    StrategyGenome,
)
from aura.execution.demo_guard import DemoExecutionGuard, LiveTradingDisabledError
from aura.execution.dhan_sandbox import (
    DhanSandboxBroker,
    DhanSandboxCredentials,
    DhanSandboxRoute,
)
from aura.runtime.evolution_supervisor import DemoEvolutionPolicy, DemoEvolutionSupervisor


def _slice(label: str, *, quality: float = 1.0, trades: int = 30) -> PerformanceSlice:
    return PerformanceSlice(
        label=label,
        trades=trades,
        net_return_pct=4.0 * quality,
        expectancy_pct=0.2 * quality,
        profit_factor=max(0.1, 1.3 * quality),
        max_drawdown_pct=max(1.0, 8.0 / max(quality, 0.1)),
        sharpe=1.2 * quality,
        win_rate=min(0.9, max(0.1, 0.55 * quality)),
        avg_slippage_bps=1.0,
    )


def _evaluation(genome: StrategyGenome, *, quality: float = 1.0) -> CandidateEvaluation:
    return CandidateEvaluation(
        genome=genome,
        in_sample=_slice("is", quality=quality, trades=100),
        walk_forward=(
            _slice("w1", quality=quality),
            _slice("w2", quality=quality),
            _slice("w3", quality=quality),
        ),
        monte_carlo_p05_return_pct=0.5 * quality,
        monte_carlo_p95_drawdown_pct=10.0,
        paper=_slice("paper", quality=quality, trades=60),
    )


def test_population_evolution_is_bounded_and_reproducible() -> None:
    specs = (
        GeneSpec(name="fast", kind=GeneKind.INTEGER, low=2, high=20),
        GeneSpec(name="slow", kind=GeneKind.INTEGER, low=21, high=80),
        GeneSpec(name="threshold", kind=GeneKind.FLOAT, low=0.1, high=1.0, step=0.1),
    )
    config = EvolutionConfig(population_size=6, random_seed=42)
    first = PopulationEvolution(specs, family="ema", config=config)
    second = PopulationEvolution(specs, family="ema", config=config)
    pop_a = first.initial_population()
    pop_b = second.initial_population()
    assert [item.parameters for item in pop_a] == [item.parameters for item in pop_b]
    evaluations = tuple(_evaluation(item) for item in pop_a)
    next_population = first.next_generation(evaluations)
    assert len(next_population) == 6
    assert all(item.generation == 1 for item in next_population)


class QualityEvaluator:
    async def evaluate(self, genome: StrategyGenome) -> CandidateEvaluation:
        fast = float(genome.parameters["fast"])
        quality = max(0.85, 1.25 - abs(fast - 8.0) / 100)
        return _evaluation(genome, quality=quality)


@pytest.mark.asyncio
async def test_demo_evolution_can_promote_paper_champion_but_never_live(tmp_path: Path) -> None:
    fitness = FitnessPolicy(min_oos_trades=60, min_paper_trades=40)
    evolution = PopulationEvolution(
        (GeneSpec(name="fast", kind=GeneKind.INTEGER, low=4, high=12),),
        family="demo",
        config=EvolutionConfig(population_size=4, random_seed=3),
        fitness_policy=fitness,
    )
    journal = EvolutionJournal(tmp_path)
    result = await DemoEvolutionSupervisor(
        evolution=evolution,
        evaluator=QualityEvaluator(),
        journal=journal,
        policy=DemoEvolutionPolicy(max_generations=2, no_improvement_patience=2),
    ).run()
    assert result.paper_champion is not None
    payload = journal.champion_path.read_text(encoding="utf-8")
    assert '"live_approved": false' in payload


def test_demo_guard_blocks_real_mt5_and_live_urls() -> None:
    DemoExecutionGuard.assert_mt5_demo_account(
        {"trade_mode": 0, "trade_allowed": True, "trade_expert": True}
    )
    with pytest.raises(LiveTradingDisabledError):
        DemoExecutionGuard.assert_mt5_demo_account({"trade_mode": 2})
    with pytest.raises(LiveTradingDisabledError):
        DemoExecutionGuard.assert_dhan_sandbox_url("https://api.dhan.co/v2")
    with pytest.raises(LiveTradingDisabledError):
        DemoExecutionGuard.assert_binance_testnet_url("https://api.binance.com")


Account = namedtuple(
    "Account",
    [
        "login",
        "trade_mode",
        "trade_allowed",
        "trade_expert",
        "server",
        "currency",
        "balance",
        "equity",
        "margin",
        "margin_free",
        "margin_level",
    ],
)


class FakeMT5:
    TIMEFRAME_M1 = 1

    def __init__(self) -> None:
        self.last_rates_call = None
        self.sent = False

    def initialize(self, *args, **kwargs):
        return True

    def shutdown(self):
        return None

    def account_info(self):
        return Account(123, 0, True, True, "Exness-Demo", "USD", 10000, 10000, 0, 10000, 0)

    def symbols_get(self):
        return ()

    def symbol_info(self, symbol):
        return None

    def symbol_info_tick(self, symbol):
        return None

    def orders_get(self, **kwargs):
        return ()

    def positions_get(self, **kwargs):
        return ()

    def order_check(self, request):
        return {"ok": True}

    def order_send(self, request):
        self.sent = True
        return {"ok": True}

    def last_error(self):
        return (0, "ok")

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.last_rates_call = (symbol, timeframe, start_pos, count)
        return [
            {
                "time": 1_700_000_000,
                "open": 2000.0,
                "high": 2002.0,
                "low": 1999.0,
                "close": 2001.0,
                "tick_volume": 100,
                "real_volume": 0,
            }
        ]


def test_mt5_demo_gateway_verifies_demo_and_reads_only_closed_bars() -> None:
    module = FakeMT5()
    gateway = OfficialMT5Gateway(module)
    state = gateway.connect_demo(MT5DemoCredentials(123, "secret", "Exness-Demo"))
    assert state.login == 123
    candles = MT5DemoClosedCandleSource(gateway).fetch("XAUUSD", "1m", count=1)
    assert module.last_rates_call == ("XAUUSD", 1, 1, 1)
    assert candles[0].closed
    gateway.order_send({"demo": True})
    assert module.sent


class FakeDhanTransport:
    def __init__(self) -> None:
        self.calls = []

    async def request(self, method, url, *, headers, payload=None):
        self.calls.append((method, url, headers, payload))
        if method == "POST":
            return {"orderId": "sandbox-1", "orderStatus": "PENDING"}
        return []


@pytest.mark.asyncio
async def test_dhan_sandbox_broker_can_only_submit_to_sandbox() -> None:
    transport = FakeDhanTransport()
    broker = DhanSandboxBroker(
        DhanSandboxCredentials("client", "token"),
        {"NIFTY": DhanSandboxRoute("13", "NSE_FNO")},
        transport=transport,
    )
    await broker.connect()
    order = OrderRequest(
        symbol="NIFTY",
        venue="DHAN_SANDBOX",
        side=Side.BUY,
        quantity=Decimal(75),
    )
    broker_id = await broker.submit_order(order)
    assert broker_id == "sandbox-1"
    assert transport.calls[0][1].startswith("https://sandbox.dhan.co/v2/")
    assert transport.calls[0][3]["quantity"] == 75
    await broker.disconnect()
