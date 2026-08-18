from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aura.agents.audit import AgentAuditJournal
from aura.agents.models import AgentRole
from aura.agents.risk_policy import AgentRiskPolicy
from aura.core.pipeline import DecisionPipeline
from aura.data.dhan_deep_service import DhanDeepMetadataService
from aura.data.dhan_history import DhanIntradayHistoryClient, resample_india_session_candles
from aura.data.dhan_option_context import (
    DhanOptionContextService,
    DhanOptionTargetResolver,
)
from aura.data.dhan_instruments import DhanInstrumentMasterDownloader
from aura.data.dhan_live_ticker import (
    DhanLiveCandleSource,
    DhanLiveCredentials,
    DhanLiveTickerSource,
    build_ticker_subscriptions,
    load_dhan_live_credentials_from_env,
)
from aura.data.dhan_universe_planner import DhanUniversePlanner, DhanUniversePolicy
from aura.data.intelligence_service import LiveIntelligenceService
from aura.execution.paper import PaperBroker, PaperExecutionConfig
from aura.evolution.brain_online import (
    BrainPaperChampionManager,
    BrainPaperPromotionPolicy,
    BrainReplayStore,
)
from aura.evolution.brain_optimizer import BrainOptimizerConfig, BrainResearchOptimizer
from aura.evolution.brain_policy import AuraBrainPolicy, BrainPolicyGate, build_brain_policy_team
from aura.evolution.brain_replay import SampleOrigin
from aura.evolution.online_bridge import OpportunityOnlineLearningBridge
from aura.evolution.online_learning import SafeOnlineLearner
from aura.evolution.opportunity_audit import (
    MissedOpportunityAuditor,
    OpportunityAuditPolicy,
    OpportunityAuditStore,
)
from aura.evolution.shadow_outcomes import ShadowDecisionOutcomeRecorder, ShadowOutcomePolicy
from aura.knowledge.firewall import KnowledgeFirewall
from aura.markets.universe import AssetClass, CanonicalInstrument
from aura.persistence.recovery import FinancialEventJournal
from aura.persistence.wal import JsonlWriteAheadLog
from aura.portfolio.instruments import AccountingMode, InstrumentLedgerSpec
from aura.portfolio.ledger import PortfolioLedger
from aura.risk.engine import RiskEngine, RiskLimits
from aura.risk.quantity import QuantityRule
from aura.runtime.allocation import PortfolioRiskCoordinator
from aura.runtime.dhan_radar import DhanOpportunityRadar, DhanRadarPolicy
from aura.runtime.learning_scanner import LearningBrainPolicyScanner
from aura.runtime.multi_market_paper import MultiMarketPaperCoordinator
from aura.runtime.scanner import MultiMarketIntelligenceScanner
from aura.strategy.ema import EmaCrossStrategy


@dataclass(slots=True, frozen=True)
class DhanSelfEvolvingPaperConfig:
    starting_cash: Decimal = Decimal(300000)
    state_dir: Path = Path("runtime/dhan_self_evolving_paper")
    broad_stream_cap: int = 5000
    broad_cash_cap: int = 3500
    broad_futures_cap: int = 1200
    deep_top_k: int = 40
    timeframes: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "4h")
    decision_timeframes: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "1h"})
    history_days: int = 35
    min_seed_1m_bars: int = 400
    max_new_history_seeds_per_radar_round: int = 8
    history_seed_retry_minutes: int = 5
    max_concurrent_contexts: int = 24
    reconcile_every_batches: int = 20
    paper_fee_bps: Decimal = Decimal(2)
    paper_slippage_bps: Decimal = Decimal(2)
    max_order_notional_pct: Decimal = Decimal(1)
    max_gross_exposure_pct: Decimal = Decimal(25)
    max_symbol_exposure_pct: Decimal = Decimal(5)
    max_drawdown_pct: Decimal = Decimal(10)
    max_daily_loss_pct: Decimal = Decimal(4)
    max_spread_bps: float = 40.0
    max_slippage_bps: float = 20.0

    def __post_init__(self) -> None:
        if self.starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        if not 1 <= self.broad_stream_cap <= 5000:
            raise ValueError("broad_stream_cap must be between 1 and 5000")
        if not 1 <= self.deep_top_k <= self.broad_stream_cap:
            raise ValueError("deep_top_k must be within the broad stream cap")
        if not self.timeframes or not self.decision_timeframes:
            raise ValueError("Dhan daemon requires timeframes and decision timeframes")
        if not self.decision_timeframes.issubset(self.timeframes):
            raise ValueError("decision timeframes must be included in timeframes")
        if self.history_days <= 0 or self.min_seed_1m_bars <= 0:
            raise ValueError("history seed settings must be positive")
        if self.max_new_history_seeds_per_radar_round <= 0:
            raise ValueError("history seed round cap must be positive")
        if self.history_seed_retry_minutes <= 0:
            raise ValueError("history_seed_retry_minutes must be positive")


@dataclass(slots=True)
class DhanPaperCounters:
    radar_batches: int = 0
    deep_batches: int = 0
    contexts: int = 0
    opportunities: int = 0
    submitted_orders: int = 0
    fills: int = 0
    reconciliations: int = 0
    history_seeded_symbols: int = 0
    history_seed_failures: int = 0


class DhanSelfEvolvingPaperDaemon:
    """Live Indian market data -> deep AURA desk -> internal paper -> evolution."""

    def __init__(
        self,
        *,
        config: DhanSelfEvolvingPaperConfig,
        broad_source: DhanLiveCandleSource,
        deep_service: DhanDeepMetadataService,
        option_service: DhanOptionContextService,
        intelligence_service: LiveIntelligenceService,
        radar: DhanOpportunityRadar,
        coordinator: MultiMarketPaperCoordinator,
        history_client: DhanIntradayHistoryClient,
        instrument_by_symbol: dict[str, CanonicalInstrument],
        instrument_type_by_symbol: dict[str, str],
        agent_risk_policy: AgentRiskPolicy,
        optimizer: BrainResearchOptimizer,
        replay_store: BrainReplayStore,
        recorder: ShadowDecisionOutcomeRecorder,
        champion_manager: BrainPaperChampionManager,
        opportunity_auditor: MissedOpportunityAuditor,
        online_bridge: OpportunityOnlineLearningBridge,
        current_policy: AuraBrainPolicy,
        research_every_new_samples: int,
    ) -> None:
        if research_every_new_samples <= 0:
            raise ValueError("research_every_new_samples must be positive")
        self.config = config
        self.broad_source = broad_source
        self.deep_service = deep_service
        self.option_service = option_service
        self.intelligence_service = intelligence_service
        self.radar = radar
        self.coordinator = coordinator
        self.history_client = history_client
        self.instrument_by_symbol = instrument_by_symbol
        self.instrument_type_by_symbol = instrument_type_by_symbol
        self.agent_risk_policy = agent_risk_policy
        self.optimizer = optimizer
        self.replay_store = replay_store
        self.recorder = recorder
        self.champion_manager = champion_manager
        self.opportunity_auditor = opportunity_auditor
        self.online_bridge = online_bridge
        self.current_policy = current_policy
        self._online_research_due = False
        self.research_every_new_samples = research_every_new_samples
        self.counters = DhanPaperCounters()
        self._seeded_symbols: set[str] = set()
        self._seed_retry_after: dict[str, datetime] = {}
        self._stop = asyncio.Event()
        self._radar_task: asyncio.Task | None = None
        self._samples_at_last_research = len(self._live_samples())
        self.status_path = config.state_dir / "status.json"
        self.brain_state_dir = config.state_dir / "brain"
        self.brain_state_dir.mkdir(parents=True, exist_ok=True)
        self._install_policy(current_policy)

    async def run(self, *, max_deep_batches: int | None = None) -> DhanPaperCounters:
        if max_deep_batches is not None and max_deep_batches <= 0:
            raise ValueError("max_deep_batches must be positive")
        self._stop.clear()
        await self.intelligence_service.start()
        await self.coordinator.start()
        self._radar_task = asyncio.create_task(self._radar_loop())
        self._write_status(None)
        try:
            async for raw_batch in self.deep_service.batches():
                if self._stop.is_set():
                    break
                batch = self._eligible_deep_batch(raw_batch)
                if not batch:
                    continue
                audited = self.opportunity_auditor.on_closed_candles(batch)
                if self.online_bridge.observe_records(audited):
                    self._online_research_due = True
                for sample in self.recorder.on_closed_candles(batch):
                    self.champion_manager.observe(sample)
                if self.champion_manager.try_promote():
                    champion = self.champion_manager.paper_champion
                    assert champion is not None
                    self.current_policy = AuraBrainPolicy.from_genome(champion)
                    self._install_policy(self.current_policy)

                step = await self.coordinator.on_batch(batch)
                scanner = self.coordinator.scanner
                if not isinstance(scanner, LearningBrainPolicyScanner):
                    raise RuntimeError("Dhan learning scanner was replaced unexpectedly")
                self.recorder.register_scan(scanner.last_raw_scan)
                self.opportunity_auditor.register_scan(scanner.last_raw_scan)

                self.counters.deep_batches += 1
                self.counters.contexts += len(step.scan.candidates)
                self.counters.opportunities += len(step.scan.opportunities)
                self.counters.submitted_orders += len(step.submitted_orders)
                self.counters.fills += len(step.fills)
                if self.counters.deep_batches % self.config.reconcile_every_batches == 0:
                    self.coordinator.reconcile()
                    self.counters.reconciliations += 1
                self._maybe_research()
                self._write_status(step)
                if max_deep_batches and self.counters.deep_batches >= max_deep_batches:
                    break
        finally:
            self._stop.set()
            self.broad_source.stop()
            await self.deep_service.stop()
            await self.option_service.stop()
            await self.intelligence_service.stop()
            if self._radar_task is not None:
                self._radar_task.cancel()
                await asyncio.gather(self._radar_task, return_exceptions=True)
            try:
                self.coordinator.reconcile()
                self.counters.reconciliations += 1
            finally:
                await self.coordinator.stop()
                self._write_status(None)
        return self.counters

    def _eligible_deep_batch(
        self,
        batch: tuple,
    ) -> tuple:
        active = set(self.deep_service.active_symbols)
        active.update(
            symbol
            for symbol, position in self.coordinator.ledger.positions.items()
            if position.quantity != 0
        )
        return tuple(candle for candle in batch if candle.symbol in active)

    async def _radar_loop(self) -> None:
        async for batch in self.broad_source.batches():
            if self._stop.is_set():
                return
            one_minute = tuple(candle for candle in batch if candle.timeframe == "1m")
            if not one_minute:
                continue
            open_positions = {
                symbol
                for symbol, position in self.coordinator.ledger.positions.items()
                if position.quantity != 0
            }
            self.radar.set_priority_symbols(open_positions)
            selection = self.radar.observe(one_minute)
            self.counters.radar_batches += 1
            requested = selection.selected_tradable_symbols
            await self._seed_requested_symbols(requested)
            ready = tuple(symbol for symbol in requested if symbol in self._seeded_symbols)
            await self.deep_service.update_symbols(ready)
            await self.option_service.update_symbols(ready)
            self._write_status(None)

    async def _seed_requested_symbols(self, symbols: tuple[str, ...]) -> None:
        now = datetime.now(UTC)
        candidates = [
            symbol
            for symbol in symbols
            if symbol not in self._seeded_symbols
            and self._seed_retry_after.get(symbol, now) <= now
        ][: self.config.max_new_history_seeds_per_radar_round]
        if not candidates:
            return
        results = await asyncio.gather(
            *(self._fetch_seed(symbol) for symbol in candidates),
            return_exceptions=True,
        )
        for symbol, result in zip(candidates, results, strict=True):
            if isinstance(result, Exception) or not result:
                self._seed_retry_after[symbol] = now + timedelta(
                    minutes=self.config.history_seed_retry_minutes
                )
                self.counters.history_seed_failures += 1
                continue
            self.coordinator.seed_histories(result)
            self._seeded_symbols.add(symbol)
            self._seed_retry_after.pop(symbol, None)
            self.counters.history_seeded_symbols += 1

    async def _fetch_seed(self, symbol: str) -> dict[tuple[str, str], tuple]:
        instrument = self.instrument_by_symbol[symbol]
        instrument_type = self.instrument_type_by_symbol.get(symbol)
        if not instrument_type:
            raise RuntimeError(f"missing exact Dhan instrument type for {symbol}")
        now = datetime.now(UTC)
        one_minute = await asyncio.to_thread(
            self.history_client.fetch,
            instrument,
            dhan_instrument_type=instrument_type,
            from_time=now - timedelta(days=self.config.history_days),
            to_time=now,
            interval_minutes=1,
            include_open_interest=instrument.asset_class == AssetClass.FUTURE,
            as_of=now,
        )
        if len(one_minute) < self.config.min_seed_1m_bars:
            return {}
        histories: dict[tuple[str, str], tuple] = {}
        for timeframe in self.config.timeframes:
            series = resample_india_session_candles(one_minute, timeframe)
            if series:
                histories[(symbol, timeframe)] = series
        return histories

    def _live_samples(self):
        return tuple(
            sample
            for sample in self.replay_store.read_all()
            if sample.origin == SampleOrigin.LIVE_BROKER
        )

    def _maybe_research(self) -> None:
        samples = self._live_samples()
        new_samples = len(samples) - self._samples_at_last_research
        if (
            new_samples < self.research_every_new_samples
            and not self._online_research_due
        ):
            return
        if len(samples) < self.optimizer.config.minimum_samples:
            return
        if self.champion_manager.challenger is not None:
            return
        result = self.optimizer.optimize(samples, baseline=self.current_policy)
        self._samples_at_last_research = len(samples)
        self._online_research_due = False
        _atomic_json(
            self.brain_state_dir / "latest_research_challenger.json",
            {
                "created_at": datetime.now(UTC).isoformat(),
                "genome": result.genome.model_dump(mode="json"),
                "genome_id": result.genome.genome_id,
                "validation_score": result.validation.score,
                "sealed_holdout_score": result.sealed_holdout.score,
                "holdout_passed": result.holdout_passed,
                "samples_used": result.samples_used,
                "sample_origin": SampleOrigin.LIVE_BROKER.value,
                "paper_validated": False,
                "live_approved": False,
            },
        )
        if result.holdout_passed:
            self.champion_manager.install_research_challenger(
                result.genome,
                research_score=result.sealed_holdout.score,
            )

    def _install_policy(self, policy: AuraBrainPolicy) -> None:
        team = build_brain_policy_team(
            KnowledgeFirewall(),
            policy,
            risk_policy=self.agent_risk_policy,
            min_top_of_book_notional=1.0,
        )
        raw_scanner = MultiMarketIntelligenceScanner(
            orchestrator=team.orchestrator,
            ceo=team.ceo,
            agent_risk_policy=team.risk_policy,
            max_concurrent_contexts=self.config.max_concurrent_contexts,
        )
        self.coordinator.scanner = LearningBrainPolicyScanner(
            raw_scanner,
            BrainPolicyGate(policy),
        )

    def _write_status(self, step) -> None:
        audit = self.opportunity_auditor.store.metrics()
        challenger = self.champion_manager.challenger
        payload = {
            "mode": "DHAN_LIVE_DATA_INTERNAL_PAPER_SELF_EVOLVING",
            "updated_at": datetime.now(UTC).isoformat(),
            "real_money_enabled": False,
            "live_approved": False,
            "validation_source_required": SampleOrigin.LIVE_BROKER.value,
            "radar": {
                "selected": list(self.radar.last_selection.selected_tradable_symbols),
                "index_context": list(self.radar.last_selection.context_index_symbols),
                "top_scores": [
                    {"symbol": item.symbol, "score": item.score}
                    for item in self.radar.last_selection.ranked[:20]
                ],
            },
            "deep_active_symbols": list(self.deep_service.active_symbols),
            "option_context": self.option_service.status(),
            "live_intelligence": self.intelligence_service.status(),
            "history_seed_retry_symbols": sorted(self._seed_retry_after),
            "counters": asdict(self.counters),
            "online_learning": self.online_bridge.status(),
            "opportunity_audit": {
                "material_opportunities": audit.material_opportunities,
                "captured": audit.captured,
                "missed_flat": audit.missed_flat,
                "wrong_direction": audit.wrong_direction,
                "blocked_safety": audit.blocked_safety,
                "capture_rate": audit.capture_rate,
                "pending": self.opportunity_auditor.pending_count,
            },
            "brain": {
                "current_genome_id": self.current_policy.to_genome().genome_id,
                "live_samples": len(self._live_samples()),
                "forward_challenger_genome_id": (
                    challenger.genome.genome_id if challenger else None
                ),
            },
            "risk_kill_switch": self.coordinator.risk_engine.kill_switch,
            "risk_kill_switch_reason": self.coordinator.risk_engine.kill_switch_reason,
        }
        if step is not None:
            payload["latest"] = {
                "close_time": step.close_time_iso,
                "portfolio_equity": str(step.portfolio.equity),
                "gross_exposure": str(step.portfolio.gross_exposure),
                "opportunities": len(step.scan.opportunities),
                "orders": len(step.submitted_orders),
                "fills": len(step.fills),
            }
        _atomic_json(self.status_path, payload)


async def build_dhan_self_evolving_paper_daemon(
    config: DhanSelfEvolvingPaperConfig | None = None,
    *,
    credentials: DhanLiveCredentials | None = None,
    optimizer_config: BrainOptimizerConfig | None = None,
    shadow_policy: ShadowOutcomePolicy | None = None,
    promotion_policy: BrainPaperPromotionPolicy | None = None,
    opportunity_audit_policy: OpportunityAuditPolicy | None = None,
    research_every_new_samples: int = 100,
) -> DhanSelfEvolvingPaperDaemon:
    config = config or DhanSelfEvolvingPaperConfig()
    config.state_dir.mkdir(parents=True, exist_ok=True)
    credentials = credentials or load_dhan_live_credentials_from_env()
    master = await asyncio.to_thread(DhanInstrumentMasterDownloader().download)
    universe = master.to_canonical_universe()
    plan = DhanUniversePlanner(
        DhanUniversePolicy(
            max_stream_instruments=config.broad_stream_cap,
            max_primary_cash_symbols=config.broad_cash_cap,
            max_primary_futures=config.broad_futures_cap,
        )
    ).primary_plan(universe)
    broad_instruments = tuple(_unique_instrument_map(plan.streamed).values())
    if not broad_instruments:
        raise RuntimeError("Dhan instrument master produced no broad live universe")
    tradable = tuple(item for item in broad_instruments if item.tradable)
    instrument_by_symbol = _unique_instrument_map(tradable)

    broad_source = DhanLiveCandleSource(
        DhanLiveTickerSource(
            credentials,
            build_ticker_subscriptions(broad_instruments),
        ),
        timeframes=("1m",),
    )
    radar = DhanOpportunityRadar(
        broad_instruments,
        policy=DhanRadarPolicy(top_k_tradable=config.deep_top_k),
    )
    deep_service = DhanDeepMetadataService(
        credentials,
        tuple(instrument_by_symbol.values()),
        timeframes=config.timeframes,
    )
    instrument_type_by_symbol = _instrument_type_map(master.records, instrument_by_symbol)
    option_service = DhanOptionContextService(
        credentials,
        DhanOptionTargetResolver(universe),
    )
    intelligence_service = LiveIntelligenceService(
        include_official_india=True,
        gdelt_queries=("India stock market", "Reserve Bank of India", "SEBI"),
    )

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

    evidence_policy = _dhan_agent_risk_policy()
    brain_dir = config.state_dir / "brain"
    replay_store = BrainReplayStore(brain_dir / "replay_samples.jsonl")
    champion_manager = BrainPaperChampionManager(
        brain_dir,
        promotion_policy=promotion_policy,
    )
    restored = champion_manager.paper_champion
    current_policy = (
        AuraBrainPolicy.from_genome(restored)
        if restored
        else AuraBrainPolicy(
            max_execution_spread_bps=config.max_spread_bps,
            max_execution_slippage_bps=config.max_slippage_bps,
        )
    )
    initial_team = build_brain_policy_team(
        KnowledgeFirewall(),
        current_policy,
        risk_policy=evidence_policy,
        min_top_of_book_notional=1.0,
    )
    scanner = LearningBrainPolicyScanner(
        MultiMarketIntelligenceScanner(
            orchestrator=initial_team.orchestrator,
            ceo=initial_team.ceo,
            agent_risk_policy=initial_team.risk_policy,
            max_concurrent_contexts=config.max_concurrent_contexts,
        ),
        BrainPolicyGate(current_policy),
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
    coordinator = MultiMarketPaperCoordinator(
        scanner=scanner,
        allocator=allocator,
        broker=broker,
        ledger=PortfolioLedger(
            config.starting_cash,
            instrument_specs={
                symbol: _ledger_spec(item)
                for symbol, item in instrument_by_symbol.items()
            },
        ),
        financial_journal=FinancialEventJournal(
            JsonlWriteAheadLog(config.state_dir / "financial.jsonl")
        ),
        agent_audit_journal=AgentAuditJournal(
            JsonlWriteAheadLog(config.state_dir / "agents.jsonl")
        ),
        risk_engine=risk_engine,
        starting_cash=config.starting_cash,
        default_requested_quantity=Decimal(1),
        requested_quantity_provider=lambda symbol: instrument_by_symbol[symbol].min_quantity,
        metadata_provider=lambda candle, _history, decision_time: _dhan_decision_metadata(
            deep_service,
            option_service,
            intelligence_service,
            candle.symbol,
            decision_time,
        ),
        decision_timeframes=config.decision_timeframes,
    )
    recorder = ShadowDecisionOutcomeRecorder(
        replay_store,
        policy=shadow_policy,
        origin=SampleOrigin.LIVE_BROKER,
    )
    auditor = MissedOpportunityAuditor(
        OpportunityAuditStore(brain_dir / "opportunity_audit.jsonl"),
        policy=opportunity_audit_policy,
    )
    online_bridge = OpportunityOnlineLearningBridge(
        SafeOnlineLearner(),
        market="INDIA",
    )
    return DhanSelfEvolvingPaperDaemon(
        config=config,
        broad_source=broad_source,
        deep_service=deep_service,
        option_service=option_service,
        intelligence_service=intelligence_service,
        radar=radar,
        coordinator=coordinator,
        history_client=DhanIntradayHistoryClient(credentials),
        instrument_by_symbol=instrument_by_symbol,
        instrument_type_by_symbol=instrument_type_by_symbol,
        agent_risk_policy=evidence_policy,
        optimizer=BrainResearchOptimizer(optimizer_config),
        replay_store=replay_store,
        recorder=recorder,
        champion_manager=champion_manager,
        opportunity_auditor=auditor,
        online_bridge=online_bridge,
        current_policy=current_policy,
        research_every_new_samples=research_every_new_samples,
    )


def _dhan_decision_metadata(
    deep_service: DhanDeepMetadataService,
    option_service: DhanOptionContextService,
    intelligence_service: LiveIntelligenceService,
    symbol: str,
    decision_time: datetime,
) -> dict:
    metadata = deep_service.metadata_for(
        symbol,
        decision_time=decision_time,
    )
    metadata.update(
        option_service.metadata_for(
            symbol,
            decision_time=decision_time,
        )
    )
    metadata.update(
        intelligence_service.metadata_for(
            symbol,
            decision_time=decision_time,
        )
    )
    return metadata


def _dhan_agent_risk_policy() -> AgentRiskPolicy:
    base = AgentRiskPolicy()
    return AgentRiskPolicy(
        required_roles=base.required_roles | {AgentRole.EXECUTION_QUALITY},
        unavailable_evidence_flags=base.unavailable_evidence_flags
        | {"execution_quality_missing"},
        hard_block_flags=base.hard_block_flags,
        min_directional_supporters=base.min_directional_supporters,
    )


def _instrument_type_map(records, instruments: dict[str, CanonicalInstrument]) -> dict[str, str]:
    by_security = {
        (record.exchange_segment, record.security_id): record.instrument_name.upper()
        for record in records
        if record.instrument_name
    }
    return {
        symbol: by_security.get((item.segment or "", item.venue_symbol), "")
        for symbol, item in instruments.items()
    }


def _unique_instrument_map(instruments) -> dict[str, CanonicalInstrument]:
    result: dict[str, CanonicalInstrument] = {}
    for item in instruments:
        prior = result.get(item.canonical_symbol)
        if prior is None or (prior.exchange == "BSE" and item.exchange == "NSE"):
            result[item.canonical_symbol] = item
    return result


def _ledger_spec(instrument: CanonicalInstrument) -> InstrumentLedgerSpec:
    if instrument.asset_class == AssetClass.OPTION:
        accounting = AccountingMode.PREMIUM
    elif instrument.asset_class == AssetClass.FUTURE:
        accounting = AccountingMode.DERIVATIVE
    else:
        accounting = AccountingMode.SPOT
    return InstrumentLedgerSpec(
        accounting=accounting,
        contract_multiplier=instrument.contract_size,
    )


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
