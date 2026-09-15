from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from aura.agents.advisory_specialists import ExecutionQualitySpecialist
from aura.agents.audit import AgentAuditJournal
from aura.agents.team import build_default_agent_team
from aura.core.pipeline import DecisionPipeline
from aura.data.mt5_demo import (
    MT5DemoCredentials,
    OfficialMT5Gateway,
    load_mt5_demo_credentials_from_env,
)
from aura.data.mt5_polling import MT5DemoPollingSource, MT5PollingPolicy
from aura.domain.models import NormalizedCandle
from aura.execution.mt5_demo_broker import MT5DemoBroker, MT5DemoBrokerConfig
from aura.knowledge.firewall import KnowledgeFirewall
from aura.persistence.recovery import FinancialEventJournal
from aura.persistence.wal import JsonlWriteAheadLog
from aura.portfolio.instruments import AccountingMode, InstrumentLedgerSpec
from aura.portfolio.ledger import PortfolioLedger
from aura.risk.engine import RiskEngine, RiskLimits
from aura.risk.quantity import QuantityRule
from aura.runtime.allocation import PortfolioRiskCoordinator
from aura.runtime.multi_market_paper import MultiMarketPaperCoordinator
from aura.runtime.scanner import MultiMarketIntelligenceScanner
from aura.strategy.ema import EmaCrossStrategy


@dataclass(slots=True, frozen=True)
class MT5AutonomousDemoConfig:
    state_dir: Path = Path("runtime/mt5_autonomous_demo")
    timeframes: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
    decision_timeframes: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "1h"})
    seed_bars: int = 250
    catchup_bars: int = 3
    max_symbols: int | None = None
    max_concurrent_contexts: int = 24
    max_order_notional_pct: Decimal = Decimal("0.50")
    max_gross_exposure_pct: Decimal = Decimal("10")
    max_symbol_exposure_pct: Decimal = Decimal("2")
    max_drawdown_pct: Decimal = Decimal("8")
    max_daily_loss_pct: Decimal = Decimal("3")
    reconcile_every_batches: int = 10
    max_spread_bps: float = 30.0
    max_estimated_slippage_bps: float = 20.0


class MT5CandleDemoBroker(MT5DemoBroker):
    """Expose broker-origin fills to the closed-candle coordinator."""

    async def on_candle(self, _candle: NormalizedCandle):
        return await __import__("asyncio").to_thread(self._poll_fills_sync)


class MT5AutonomousDemoDaemon:
    """AURA closed-candle intelligence -> RiskEngine -> actual MT5 DEMO orders.

    This runtime cannot connect to a live-money MT5 account: OfficialMT5Gateway
    verifies DEMO before any order API is enabled. It discovers the broker's
    entire tradable universe, consumes broker-origin market data, runs the AURA
    specialist/CEO stack, serializes opportunities through the central RiskEngine,
    submits approved market orders to MT5 DEMO, records broker fills, and performs
    reconciliation. Existing orders/positions cause startup refusal so AURA does
    not silently take control of a shared/manual demo account.
    """

    def __init__(self, *, config: MT5AutonomousDemoConfig, gateway: OfficialMT5Gateway,
                 source: MT5DemoPollingSource, coordinator: MultiMarketPaperCoordinator,
                 account_login: int, account_server: str, active_symbols: int) -> None:
        self.config = config
        self.gateway = gateway
        self.source = source
        self.coordinator = coordinator
        self.account_login = account_login
        self.account_server = account_server
        self.active_symbols = active_symbols
        self.status_path = config.state_dir / "status.json"
        self.batches = 0
        self.orders = 0
        self.fills = 0

    async def run(self, *, max_batches: int | None = None) -> None:
        await self.coordinator.start()
        self._write_status("running")
        try:
            async for batch in self.source.batches():
                step = await self.coordinator.on_batch(batch)
                self.batches += 1
                self.orders += len(step.submitted_orders)
                self.fills += len(step.fills)
                if self.batches % self.config.reconcile_every_batches == 0:
                    self.coordinator.reconcile()
                self._write_status("running")
                if max_batches is not None and self.batches >= max_batches:
                    self.source.stop()
                    break
        finally:
            try:
                self.coordinator.reconcile()
            finally:
                await self.coordinator.stop()
                self.gateway.shutdown()
                self._write_status("stopped")

    def _write_status(self, state: str) -> None:
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "state": state,
            "mode": "MT5_REAL_MARKET_DATA_ACTUAL_DEMO_ORDERS",
            "real_money_enabled": False,
            "demo_account_verified": True,
            "account_login": self.account_login,
            "account_server": self.account_server,
            "active_symbols": self.active_symbols,
            "batches": self.batches,
            "orders": self.orders,
            "fills": self.fills,
            "risk_kill_switch": self.coordinator.risk_engine.kill_switch,
            "risk_kill_switch_reason": self.coordinator.risk_engine.kill_switch_reason,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        tmp = self.status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.status_path)


async def build_mt5_autonomous_demo_daemon(
    config: MT5AutonomousDemoConfig | None = None,
    *,
    credentials: MT5DemoCredentials | None = None,
    gateway: OfficialMT5Gateway | None = None,
) -> MT5AutonomousDemoDaemon:
    config = config or MT5AutonomousDemoConfig()
    if not config.decision_timeframes.issubset(config.timeframes):
        raise ValueError("decision_timeframes must be included in timeframes")
    config.state_dir.mkdir(parents=True, exist_ok=True)
    gateway = gateway or OfficialMT5Gateway()
    account = gateway.connect_demo(credentials or load_mt5_demo_credentials_from_env())
    try:
        if gateway.orders_get():
            raise RuntimeError("MT5 DEMO startup refused: close/cancel existing orders first")
        if gateway.positions_get():
            raise RuntimeError("MT5 DEMO startup refused: close existing positions first")

        discovered = tuple(item for item in gateway.discover_universe() if item.tradable)
        if not discovered:
            raise RuntimeError("MT5 DEMO account exposed no tradable instruments")
        selected = discovered[: config.max_symbols] if config.max_symbols else discovered
        by_symbol = {item.venue_symbol: item for item in selected}
        symbols = tuple(sorted(by_symbol))
        specs = {
            symbol: InstrumentLedgerSpec(
                accounting=AccountingMode.DERIVATIVE,
                contract_multiplier=item.contract_size,
            )
            for symbol, item in by_symbol.items()
        }
        multipliers = {symbol: item.contract_size for symbol, item in by_symbol.items()}
        quantity_rules = {
            symbol: QuantityRule(
                minimum=item.min_quantity,
                step=item.quantity_step,
                maximum=item.max_quantity,
            )
            for symbol, item in by_symbol.items()
        }
        risk = RiskEngine(
            RiskLimits(
                max_order_notional_pct=config.max_order_notional_pct,
                max_gross_exposure_pct=config.max_gross_exposure_pct,
                max_symbol_exposure_pct=config.max_symbol_exposure_pct,
                max_drawdown_pct=config.max_drawdown_pct,
                max_daily_loss_pct=config.max_daily_loss_pct,
            ),
            notional_multipliers=multipliers,
            quantity_rules=quantity_rules,
        )
        source = MT5DemoPollingSource(
            gateway,
            symbols,
            policy=MT5PollingPolicy(
                timeframes=config.timeframes,
                seed_bars=config.seed_bars,
                catchup_bars=config.catchup_bars,
            ),
        )
        seed = await source.seed_histories()
        if not seed.histories:
            raise RuntimeError("MT5 DEMO history seed produced no usable series")

        team = build_default_agent_team(
            KnowledgeFirewall(),
            execution_quality_specialist=ExecutionQualitySpecialist(
                max_spread_bps=config.max_spread_bps,
                max_estimated_slippage_bps=config.max_estimated_slippage_bps,
                min_top_of_book_notional=0.0,
            ),
        )
        scanner = MultiMarketIntelligenceScanner(
            orchestrator=team.orchestrator,
            ceo=team.ceo,
            agent_risk_policy=team.risk_policy,
            max_concurrent_contexts=config.max_concurrent_contexts,
        )
        allocator = PortfolioRiskCoordinator(
            DecisionPipeline(EmaCrossStrategy(fast=8, slow=21), risk)
        )
        broker = MT5CandleDemoBroker(
            gateway,
            config=MT5DemoBrokerConfig(comment_prefix="AURA"),
        )
        coordinator = MultiMarketPaperCoordinator(
            scanner=scanner,
            allocator=allocator,
            broker=broker,  # runtime-compatible BrokerAdapter with on_candle
            ledger=PortfolioLedger(account.balance, instrument_specs=specs),
            financial_journal=FinancialEventJournal(
                JsonlWriteAheadLog(config.state_dir / "financial.jsonl")
            ),
            agent_audit_journal=AgentAuditJournal(
                JsonlWriteAheadLog(config.state_dir / "agents.jsonl")
            ),
            risk_engine=risk,
            starting_cash=account.balance,
            default_requested_quantity=min(item.min_quantity for item in by_symbol.values()),
            requested_quantity_provider=lambda symbol: by_symbol[symbol].min_quantity,
            metadata_provider=lambda candle, _history, _decision_time: source.metadata_for(candle.symbol),
            decision_timeframes=config.decision_timeframes,
        )
        coordinator.seed_histories(seed.histories)
        return MT5AutonomousDemoDaemon(
            config=config,
            gateway=gateway,
            source=source,
            coordinator=coordinator,
            account_login=account.login,
            account_server=account.server,
            active_symbols=len(symbols),
        )
    except Exception:
        gateway.shutdown()
        raise
