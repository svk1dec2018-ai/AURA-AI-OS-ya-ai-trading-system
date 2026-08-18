from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aura.agents.audit import AgentAuditJournal
from aura.core.pipeline import DecisionPipeline
from aura.data.mt5_demo import MT5DemoCredentials, OfficialMT5Gateway
from aura.data.mt5_polling import MT5DemoPollingSource, MT5PollingPolicy
from aura.domain.models import NormalizedCandle, OrderRequest, Side
from aura.execution.mt5_demo_broker import MT5DemoBroker
from aura.execution.paper import PaperBroker
from aura.persistence.recovery import FinancialEventJournal
from aura.persistence.wal import JsonlWriteAheadLog
from aura.portfolio.ledger import PortfolioLedger
from aura.risk.engine import RiskEngine, RiskLimits
from aura.runtime.allocation import PortfolioRiskCoordinator
from aura.runtime.multi_market_paper import MultiMarketPaperCoordinator
from aura.runtime.scanner import MarketScanResult
from aura.strategy.ema import EmaCrossStrategy


class FakeMT5:
    TIMEFRAME_M1 = 1
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_REMOVE = 8
    ORDER_TIME_GTC = 0
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TYPE_BUY_STOP = 4
    ORDER_TYPE_SELL_STOP = 5
    ORDER_TYPE_BUY_STOP_LIMIT = 6
    ORDER_TYPE_SELL_STOP_LIMIT = 7
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    SYMBOL_TRADE_EXECUTION_MARKET = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_PLACED = 10008
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    DEAL_TYPE_BUY = 0
    DEAL_TYPE_SELL = 1

    def __init__(self) -> None:
        self.sent_request = None
        self.last_rates_call = None
        self._order_ticket = 9001
        self._bars = [
            {
                "time": 1_700_000_000,
                "open": 2000,
                "high": 2002,
                "low": 1999,
                "close": 2001,
                "tick_volume": 111,
                "real_volume": 0,
            },
            {
                "time": 1_700_000_060,
                "open": 2001,
                "high": 2004,
                "low": 2000,
                "close": 2003,
                "tick_volume": 120,
                "real_volume": 0,
            },
        ]

    def initialize(self, *args, **kwargs):
        return True

    def shutdown(self):
        return None

    def account_info(self):
        return {
            "login": 123,
            "trade_mode": 0,
            "trade_allowed": True,
            "trade_expert": True,
            "server": "Exness-Demo",
            "currency": "USD",
            "balance": 10000,
            "equity": 10000,
            "margin": 0,
            "margin_free": 10000,
            "margin_level": 0,
        }

    def terminal_info(self):
        return {"connected": True}

    def symbols_get(self):
        return ()

    def symbol_info(self, symbol):
        return {
            "name": symbol,
            "visible": True,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "trade_exemode": self.SYMBOL_TRADE_EXECUTION_MARKET,
            "filling_mode": self.SYMBOL_FILLING_IOC | self.SYMBOL_FILLING_FOK,
        }

    def symbol_info_tick(self, symbol):
        return {"ask": 2000.2, "bid": 2000.0}

    def symbol_select(self, symbol, enable):
        return True

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.last_rates_call = (symbol, timeframe, start_pos, count)
        return self._bars[-count:]

    def orders_get(self, **kwargs):
        return ()

    def positions_get(self, **kwargs):
        if self.sent_request is None:
            return ()
        return ({"symbol": "XAUUSD", "volume": 0.01, "type": self.POSITION_TYPE_BUY},)

    def history_deals_get(self, *args, **kwargs):
        if self.sent_request is None:
            return ()
        return (
            {
                "ticket": 7001,
                "order": self._order_ticket,
                "type": self.DEAL_TYPE_BUY,
                "symbol": "XAUUSD",
                "volume": 0.01,
                "price": 2000.2,
                "commission": -0.1,
                "fee": 0,
                "time_msc": 1_700_000_100_000,
                "comment": self.sent_request["comment"],
            },
        )

    def order_calc_margin(self, action, symbol, volume, price):
        return 20.0

    def order_calc_profit(self, action, symbol, volume, price_open, price_close):
        return (price_close - price_open) * volume * 100

    def order_check(self, request):
        return {"retcode": 0, "comment": "Done"}

    def order_send(self, request):
        self.sent_request = request
        return {
            "retcode": self.TRADE_RETCODE_DONE,
            "order": self._order_ticket,
            "deal": 7001,
            "comment": "Done",
        }

    def last_error(self):
        return (0, "ok")


def _gateway() -> tuple[OfficialMT5Gateway, FakeMT5]:
    module = FakeMT5()
    gateway = OfficialMT5Gateway(module)
    gateway.connect_demo(MT5DemoCredentials(123, "secret", "Exness-Demo"))
    return gateway, module


@pytest.mark.asyncio
async def test_mt5_demo_broker_checks_sends_and_rebuilds_fill() -> None:
    gateway, module = _gateway()
    broker = MT5DemoBroker(gateway)
    await broker.connect()
    order = OrderRequest(
        symbol="XAUUSD",
        venue="EXNESS_MT5_DEMO",
        side=Side.BUY,
        quantity=Decimal("0.01"),
    )
    ticket = await broker.submit_order(order)
    assert ticket == "9001"
    assert module.sent_request["action"] == module.TRADE_ACTION_DEAL
    assert module.sent_request["type_filling"] == module.ORDER_FILLING_IOC
    assert "price" not in module.sent_request

    generator = broker.fills()
    fill = await anext(generator)
    assert fill.order_id == order.order_id
    assert fill.quantity == Decimal("0.01")
    assert fill.fee == Decimal("0.1")
    assert broker.position_snapshots()[0].quantity == Decimal("0.01")
    assert await broker.margin_required(order) == Decimal("20.0")
    await broker.disconnect()
    await generator.aclose()


@pytest.mark.asyncio
async def test_mt5_demo_broker_rejects_misaligned_volume() -> None:
    gateway, _ = _gateway()
    broker = MT5DemoBroker(gateway)
    await broker.connect()
    order = OrderRequest(
        symbol="XAUUSD",
        venue="EXNESS_MT5_DEMO",
        side=Side.BUY,
        quantity=Decimal("0.015"),
    )
    with pytest.raises(ValueError, match="not aligned"):
        await broker.submit_order(order)
    await broker.disconnect()


@pytest.mark.asyncio
async def test_mt5_polling_seed_uses_closed_bars_and_tick_volume_fallback() -> None:
    gateway, module = _gateway()
    source = MT5DemoPollingSource(
        gateway,
        ["XAUUSD"],
        policy=MT5PollingPolicy(
            timeframes=("1m",),
            seed_bars=2,
            catchup_bars=2,
            idle_sleep_seconds=0.01,
            poll_seconds={"1m": 1.0},
        ),
    )
    seeded = await source.seed_histories()
    history = seeded.histories[("XAUUSD", "1m")]
    assert module.last_rates_call == ("XAUUSD", 1, 1, 2)
    assert history[-1].volume == Decimal(120)
    assert history[-1].closed

    module._bars.append(
        {
            "time": 1_700_000_120,
            "open": 2003,
            "high": 2005,
            "low": 2002,
            "close": 2004,
            "tick_volume": 130,
            "real_volume": 0,
        }
    )
    grouped, issues = source._poll_sync(("1m",))
    assert not issues
    assert sum(len(batch) for batch in grouped.values()) == 1


class RecordingScanner:
    def __init__(self) -> None:
        self.contexts = ()

    async def scan(self, contexts):
        self.contexts = tuple(contexts)
        return MarketScanResult(candidates=())


def _candle(symbol: str, timeframe: str, close_time: datetime, close: str) -> NormalizedCandle:
    duration = timedelta(minutes=1 if timeframe == "1m" else 5)
    price = Decimal(close)
    return NormalizedCandle(
        symbol=symbol,
        venue="EXNESS_MT5_DEMO",
        timeframe=timeframe,
        open_time=close_time - duration,
        close_time=close_time,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal(100),
        closed=True,
    )


@pytest.mark.asyncio
async def test_seeded_coordinator_exposes_same_timestamp_htf_without_replay_trades(
    tmp_path: Path,
) -> None:
    scanner = RecordingScanner()
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(100),
            max_symbol_exposure_pct=Decimal(100),
        )
    )
    allocator = PortfolioRiskCoordinator(
        DecisionPipeline(EmaCrossStrategy(fast=2, slow=3), risk)
    )
    broker = PaperBroker()
    coordinator = MultiMarketPaperCoordinator(
        scanner=scanner,
        allocator=allocator,
        broker=broker,
        ledger=PortfolioLedger(Decimal(10000)),
        financial_journal=FinancialEventJournal(JsonlWriteAheadLog(tmp_path / "financial.jsonl")),
        agent_audit_journal=AgentAuditJournal(JsonlWriteAheadLog(tmp_path / "agents.jsonl")),
        risk_engine=risk,
        starting_cash=Decimal(10000),
        default_requested_quantity=Decimal(1),
        decision_timeframes=frozenset({"1m"}),
    )
    base = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    coordinator.seed_histories(
        {
            ("XAUUSD", "1m"): tuple(
                _candle("XAUUSD", "1m", base - timedelta(minutes=i), "2000")
                for i in range(20, 0, -1)
            ),
            ("XAUUSD", "5m"): tuple(
                _candle("XAUUSD", "5m", base - timedelta(minutes=5 * i), "2000")
                for i in range(20, 0, -1)
            ),
        }
    )
    await coordinator.start()
    close_time = base + timedelta(minutes=5)
    await coordinator.on_batch(
        (
            _candle("XAUUSD", "1m", close_time, "2001"),
            _candle("XAUUSD", "5m", close_time, "2001"),
        )
    )
    await coordinator.stop()
    assert len(scanner.contexts) == 1
    context = scanner.contexts[0]
    assert context.decision_timeframe == "1m"
    assert context.metadata["htf_candles"][-1].close_time == close_time
    assert not broker.position_snapshots()
