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
from aura.execution.paper import PaperBroker, PaperExecutionConfig
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
class MT5AllMarketPaperConfig:
    starting_cash: Decimal = Decimal(10000)
    state_dir: Path = Path("runtime/mt5_all_market_paper")
    timeframes: tuple[str, ...] = (
        "1m",
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "1d",
        "1w",
    )
    decision_timeframes: frozenset[str] = frozenset(
        {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
    )
    seed_bars: int = 250
    catchup_bars: int = 3
    max_symbols: int | None = None
    max_concurrent_contexts: int = 32
    paper_fee_bps: Decimal = Decimal(0)
    paper_slippage_bps: Decimal = Decimal(1)
    max_order_notional_pct: Decimal = Decimal(1)
    max_gross_exposure_pct: Decimal = Decimal(25)
    max_symbol_exposure_pct: Decimal = Decimal(5)
    max_drawdown_pct: Decimal = Decimal(10)
    max_daily_loss_pct: Decimal = Decimal(4)
    reconcile_every_batches: int = 20
    max_spread_bps: float = 25.0
    max_estimated_slippage_bps: float = 15.0

    def __post_init__(self) -> None:
        if self.starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        if not self.timeframes or not self.decision_timeframes:
            raise ValueError("paper daemon requires timeframes and decision_timeframes")
        if not self.decision_timeframes.issubset(self.timeframes):
            raise ValueError("decision_timeframes must be included in timeframes")
        if self.seed_bars <= 0 or self.catchup_bars <= 0:
            raise ValueError("seed/catchup bars must be positive")
        if self.max_symbols is not None and self.max_symbols <= 0:
            raise ValueError("max_symbols must be positive when configured")
        if self.max_concurrent_contexts <= 0 or self.reconcile_every_batches <= 0:
            raise ValueError("concurrency/reconciliation cadence must be positive")


@dataclass(slots=True, frozen=True)
class MT5PaperBootstrap:
    account_login: int
    account_server: str
    account_currency: str
    discovered_symbols: int
    active_symbols: int
    seed_series: int
    seed_issues: int


@dataclass(slots=True)
class MT5PaperCounters:
    batches: int = 0
    contexts: int = 0
    opportunities: int = 0
    submitted_orders: int = 0
    fills: int = 0
    reconciliations: int = 0


class MT5AllMarketPaperDaemon:
    """AURA all-market scanner on live Exness/MT5 demo data with simulated fills.

    The daemon discovers every tradable symbol exposed by the verified demo
    account, seeds causal multi-timeframe history, runs the ten-specialist AURA
    desk, adversarial deliberation and central RiskEngine, then executes only in
    AURA's internal PaperBroker. It writes durable financial/agent audit state and
    periodic status snapshots. No real-money broker route exists in this daemon.
    """

    def __init__(
        self,
        *,
        config: MT5AllMarketPaperConfig,
        gateway: OfficialMT5Gateway,
        source: MT5DemoPollingSource,
        coordinator: MultiMarketPaperCoordinator,
        bootstrap: MT5PaperBootstrap,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.source = source
        self.coordinator = coordinator
        self.bootstrap = bootstrap
        self.counters = MT5PaperCounters()
        self.status_path = config.state_dir / "status.json"
        self._running = False

    async def run(self, *, max_batches: int | None = None) -> MT5PaperCounters:
        if max_batches is not None and max_batches <= 0:
            raise ValueError("max_batches must be positive")
        if self._running:
            raise RuntimeError("MT5 paper daemon is already running")
        self._running = True
        await self.coordinator.start()
        self._write_status(None)
        try:
            async for batch in self.source.batches():
                step = await self.coordinator.on_batch(batch)
                self.counters.batches += 1
                self.counters.contexts += len(step.scan.candidates)
                self.counters.opportunities += len(step.scan.opportunities)
                self.counters.submitted_orders += len(step.submitted_orders)
                self.counters.fills += len(step.fills)

                if self.counters.batches % self.config.reconcile_every_batches == 0:
                    self.coordinator.reconcile()
                    self.counters.reconciliations += 1
                self._write_status(step)

                if max_batches is not None and self.counters.batches >= max_batches:
                    self.source.stop()
                    break
        finally:
            try:
                self.coordinator.reconcile()
                self.counters.reconciliations += 1
            finally:
                await self.coordinator.stop()
                self.gateway.shutdown()
                self._running = False
                self._write_status(None)
        return self.counters

    def _write_status(self, step) -> None:
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "mode": "MT5_LIVE_DATA_INTERNAL_PAPER_ONLY",
            "real_money_enabled": False,
            "updated_at": datetime.now(UTC).isoformat(),
            "bootstrap": {
                "account_login": self.bootstrap.account_login,
                "account_server": self.bootstrap.account_server,
                "account_currency": self.bootstrap.account_currency,
                "discovered_symbols": self.bootstrap.discovered_symbols,
                "active_symbols": self.bootstrap.active_symbols,
                "seed_series": self.bootstrap.seed_series,
                "seed_issues": self.bootstrap.seed_issues,
            },
            "counters": {
                "batches": self.counters.batches,
                "contexts": self.counters.contexts,
                "opportunities": self.counters.opportunities,
                "submitted_orders": self.counters.submitted_orders,
                "fills": self.counters.fills,
                "reconciliations": self.counters.reconciliations,
            },
            "risk_kill_switch": self.coordinator.risk_engine.kill_switch,
            "risk_kill_switch_reason": self.coordinator.risk_engine.kill_switch_reason,
            "polling_issues": [
                {
                    "symbol": issue.symbol,
                    "timeframe": issue.timeframe,
                    "detail": issue.detail,
                }
                for issue in self.source.last_issues[:100]
            ],
        }
        if step is not None:
            payload["latest"] = {
                "close_time": step.close_time_iso,
                "portfolio_equity": str(step.portfolio.equity),
                "gross_exposure": str(step.portfolio.gross_exposure),
                "drawdown_pct": str(step.portfolio.drawdown_pct),
                "opportunities": [
                    {
                        "symbol": candidate.context.symbol,
                        "timeframe": candidate.context.decision_timeframe,
                        "intent": candidate.memo.intent.value,
                        "confidence": candidate.memo.confidence,
                        "agent_policy_allowed": (
                            candidate.agent_policy.allowed
                            if candidate.agent_policy is not None
                            else None
                        ),
                    }
                    for candidate in step.scan.opportunities[:50]
                ],
                "submitted_orders": [
                    {
                        "symbol": item.order.symbol,
                        "side": item.order.side.value,
                        "quantity": str(item.order.quantity),
                        "broker_order_id": item.broker_order_id,
                    }
                    for item in step.submitted_orders
                ],
            }
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.status_path)


async def build_mt5_all_market_paper_daemon(
    config: MT5AllMarketPaperConfig | None = None,
    *,
    credentials: MT5DemoCredentials | None = None,
    gateway: OfficialMT5Gateway | None = None,
) -> MT5AllMarketPaperDaemon:
    config = config or MT5AllMarketPaperConfig()
    config.state_dir.mkdir(parents=True, exist_ok=True)
    gateway = gateway or OfficialMT5Gateway()
    account = gateway.connect_demo(credentials or load_mt5_demo_credentials_from_env())

    try:
        discovered = tuple(item for item in gateway.discover_universe() if item.tradable)
        if not discovered:
            raise RuntimeError("MT5 demo account exposed no tradable instruments")
        selected = discovered[: config.max_symbols] if config.max_symbols else discovered
        instrument_by_symbol = {item.venue_symbol: item for item in selected}
        symbols = tuple(sorted(instrument_by_symbol))

        instrument_specs = {
            symbol: InstrumentLedgerSpec(
                accounting=AccountingMode.DERIVATIVE,
                contract_multiplier=item.contract_size,
            )
            for symbol, item in instrument_by_symbol.items()
        }
        multipliers = {
            symbol: item.contract_size for symbol, item in instrument_by_symbol.items()
        }
        quantity_rules = {
            symbol: QuantityRule(
                minimum=item.min_quantity,
                step=item.quantity_step,
                maximum=item.max_quantity,
            )
            for symbol, item in instrument_by_symbol.items()
        }

        risk_engine = RiskEngine(
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
            raise RuntimeError("MT5 demo history seed produced no usable series")

        firewall = KnowledgeFirewall()
        team = build_default_agent_team(
            firewall,
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
            DecisionPipeline(EmaCrossStrategy(fast=8, slow=21), risk_engine)
        )
        broker = PaperBroker(
            PaperExecutionConfig(
                fee_bps=config.paper_fee_bps,
                slippage_bps=config.paper_slippage_bps,
            ),
            contract_multipliers=multipliers,
        )
        ledger = PortfolioLedger(
            config.starting_cash,
            instrument_specs=instrument_specs,
        )
        coordinator = MultiMarketPaperCoordinator(
            scanner=scanner,
            allocator=allocator,
            broker=broker,
            ledger=ledger,
            financial_journal=FinancialEventJournal(
                JsonlWriteAheadLog(config.state_dir / "financial.jsonl")
            ),
            agent_audit_journal=AgentAuditJournal(
                JsonlWriteAheadLog(config.state_dir / "agents.jsonl")
            ),
            risk_engine=risk_engine,
            starting_cash=config.starting_cash,
            default_requested_quantity=min(
                item.min_quantity for item in instrument_by_symbol.values()
            ),
            requested_quantity_provider=lambda symbol: instrument_by_symbol[
                symbol
            ].min_quantity,
            metadata_provider=lambda candle, _history, _decision_time: source.metadata_for(
                candle.symbol
            ),
            decision_timeframes=config.decision_timeframes,
        )
        coordinator.seed_histories(seed.histories)

        bootstrap = MT5PaperBootstrap(
            account_login=account.login,
            account_server=account.server,
            account_currency=account.currency,
            discovered_symbols=len(discovered),
            active_symbols=len(symbols),
            seed_series=len(seed.histories),
            seed_issues=len(seed.issues),
        )
        return MT5AllMarketPaperDaemon(
            config=config,
            gateway=gateway,
            source=source,
            coordinator=coordinator,
            bootstrap=bootstrap,
        )
    except Exception:
        gateway.shutdown()
        raise
