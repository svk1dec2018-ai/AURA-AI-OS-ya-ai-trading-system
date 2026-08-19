from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import log
from pathlib import Path
from typing import Any

from aura.agents.models import AgentContext
from aura.agents.reliability import AgentReliabilityTracker
from aura.agents.team import build_default_agent_team
from aura.data.candle_aggregation import SessionCandleAggregator
from aura.data.intelligence_service import LiveIntelligenceService
from aura.data.public_crypto_feeds import BybitPublicTradeFeed, CoinbasePublicTradeFeed
from aura.data.public_history import (
    BybitSpotHistoryClient,
    CoinbaseExchangeHistoryClient,
    HistoricalCandleArchive,
    PublicHistoryClient,
)
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.evolution.brain_online import BrainReplayStore
from aura.evolution.brain_replay import SampleOrigin
from aura.evolution.online_bridge import OpportunityOnlineLearningBridge
from aura.evolution.online_learning import SafeOnlineLearner
from aura.evolution.opportunity_audit import (
    MissedOpportunityAuditor,
    OpportunityAuditPolicy,
    OpportunityAuditStore,
)
from aura.evolution.shadow_outcomes import (
    ShadowDecisionOutcomeRecorder,
    ShadowOutcomePolicy,
)
from aura.forecast.baselines import (
    DriftBaselineForecastProvider,
    EmaTrendBaselineForecastProvider,
)
from aura.forecast.providers import ConcurrentForecastService
from aura.knowledge.firewall import KnowledgeFirewall
from aura.knowledge.local_corpus import LocalKnowledgeIndex
from aura.runtime.scanner import MultiMarketIntelligenceScanner


@dataclass(slots=True, frozen=True)
class FreePublicAICouncilConfig:
    provider: str = "coinbase"
    symbols: tuple[str, ...] = ("BTC-USD",)
    decision_timeframe: str = "1s"
    timeframes: tuple[str, ...] = ("1s", "5s", "15s", "30s", "1m", "5m", "15m")
    htf_timeframe: str = "5m"
    min_history_bars: int = 30
    analyze_every_bars: int = 5
    max_history_bars: int = 300
    history_seed_bars: int = 240
    forecast_horizon_bars: int = 5
    max_inflight_ai_decisions: int = 1
    enable_public_history: bool = True
    enable_live_intelligence: bool = True
    include_official_india_intelligence: bool = True
    gdelt_queries: tuple[str, ...] = (
        "bitcoin OR ethereum OR cryptocurrency",
        '"central bank" OR inflation OR interest rates',
    )
    intelligence_poll_seconds: float = 300.0
    enable_local_knowledge: bool = True
    knowledge_dir: Path = Path("knowledge/public_corpus")
    knowledge_limit: int = 6
    state_dir: Path = Path("runtime/free_public_ai_council")

    def __post_init__(self) -> None:
        if self.provider not in {"coinbase", "bybit"}:
            raise ValueError("provider must be coinbase or bybit")
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        if self.decision_timeframe not in self.timeframes:
            raise ValueError("decision_timeframe must be present in timeframes")
        if self.htf_timeframe not in self.timeframes:
            raise ValueError("htf_timeframe must be present in timeframes")
        if self.htf_timeframe == self.decision_timeframe:
            raise ValueError("htf_timeframe must differ from decision_timeframe")
        if self.min_history_bars < 10:
            raise ValueError("min_history_bars must be at least 10")
        if self.analyze_every_bars <= 0 or self.max_history_bars < self.min_history_bars:
            raise ValueError("invalid analysis/history settings")
        if not 1 <= self.history_seed_bars <= self.max_history_bars:
            raise ValueError("history_seed_bars must be within max_history_bars")
        if self.forecast_horizon_bars <= 0:
            raise ValueError("forecast_horizon_bars must be positive")
        if self.max_inflight_ai_decisions <= 0:
            raise ValueError("max_inflight_ai_decisions must be positive")
        if self.intelligence_poll_seconds <= 0:
            raise ValueError("intelligence_poll_seconds must be positive")
        if self.knowledge_limit <= 0:
            raise ValueError("knowledge_limit must be positive")


@dataclass(slots=True)
class FreePublicAICouncilCounters:
    ticks: int = 0
    closed_candles: int = 0
    ai_decisions_started: int = 0
    ai_decisions_completed: int = 0
    actionable_decisions: int = 0
    skipped_ai_due_capacity: int = 0
    opportunity_outcomes_resolved: int = 0
    research_triggers: int = 0


class FreePublicAICouncilRuntime:
    """No-key live public market data -> deterministic desk + local multi-AI council.

    Market ingestion keeps running while deep AI analyses execute in bounded
    background tasks. Public live outcomes train bounded advisory reliability but
    never satisfy broker-live strategy promotion. No broker orders are created.
    """

    def __init__(
        self,
        config: FreePublicAICouncilConfig | None = None,
        *,
        feed: Any | None = None,
        history_client: PublicHistoryClient | None = None,
        intelligence_service: LiveIntelligenceService | None = None,
        forecast_service: ConcurrentForecastService | None = None,
    ) -> None:
        self.config = config or FreePublicAICouncilConfig()
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        brain_dir = self.config.state_dir / "brain"
        self.reliability_tracker = AgentReliabilityTracker(
            brain_dir / "agent_reliability.jsonl"
        )
        self.replay_store = BrainReplayStore(brain_dir / "replay_samples.jsonl")
        self.recorder = ShadowDecisionOutcomeRecorder(
            self.replay_store,
            policy=ShadowOutcomePolicy(horizon_bars=5),
            origin=SampleOrigin.LIVE_PUBLIC,
            reliability_tracker=self.reliability_tracker,
        )
        self.opportunity_store = OpportunityAuditStore(
            brain_dir / "opportunity_audit.jsonl"
        )
        self.opportunity_auditor = MissedOpportunityAuditor(
            self.opportunity_store,
            policy=OpportunityAuditPolicy(horizon_bars=5),
        )
        self.online_learner = SafeOnlineLearner()
        self.online_bridge = OpportunityOnlineLearningBridge(
            self.online_learner,
            market=f"{self.config.provider}_public",
        )
        self.online_bridge.replay_records(self.opportunity_store.read_all())
        self.knowledge_load_error: str | None = None
        self.knowledge_ingest_errors: list[str] = []
        self.knowledge_index = LocalKnowledgeIndex()
        if self.config.enable_local_knowledge:
            try:
                self.knowledge_index = LocalKnowledgeIndex.load(
                    self.config.knowledge_dir
                )
            except Exception as exc:  # noqa: BLE001 - optional corpus isolation
                self.knowledge_load_error = f"{type(exc).__name__}: {exc}"
        self.knowledge_firewall = KnowledgeFirewall()
        for item in self.knowledge_index.items:
            try:
                self.knowledge_firewall.ingest(item)
            except Exception as exc:  # noqa: BLE001 - one source cannot poison corpus
                self.knowledge_ingest_errors.append(
                    f"{item.item_id}: {type(exc).__name__}: {exc}"
                )
        team = build_default_agent_team(
            self.knowledge_firewall,
            include_env_ai=True,
            reliability_tracker=self.reliability_tracker,
        )
        ai_agents = tuple(
            item for item in team.agents if item.agent_id.startswith("ai-council:")
        )
        if not ai_agents:
            raise RuntimeError(
                "AURA_OLLAMA_MODELS is not configured; multi-AI public runtime requires local models"
            )
        self.team = team
        self.ai_agent_count = len(ai_agents)
        self.scanner = MultiMarketIntelligenceScanner(
            orchestrator=team.orchestrator,
            ceo=team.ceo,
            agent_risk_policy=team.risk_policy,
            max_concurrent_contexts=self.config.max_inflight_ai_decisions,
        )
        self.feed = feed or self._build_feed()
        self.history_client = history_client or self._build_history_client()
        self.history_archive = HistoricalCandleArchive(
            self.config.state_dir / "historical_candles"
        )
        self.intelligence_service = intelligence_service or LiveIntelligenceService(
            include_official_india=self.config.include_official_india_intelligence,
            gdelt_queries=self.config.gdelt_queries,
            poll_interval_seconds=self.config.intelligence_poll_seconds,
        )
        self.forecast_service = forecast_service or ConcurrentForecastService(
            (
                DriftBaselineForecastProvider(),
                EmaTrendBaselineForecastProvider(),
            )
        )
        self.aggregator = SessionCandleAggregator(timeframes=self.config.timeframes)
        self.histories: dict[tuple[str, str], deque[NormalizedCandle]] = defaultdict(
            lambda: deque(maxlen=self.config.max_history_bars)
        )
        self.bar_counts: dict[tuple[str, str], int] = defaultdict(int)
        self.counters = FreePublicAICouncilCounters()
        self.status_path = self.config.state_dir / "status.json"
        self._inflight: set[asyncio.Task] = set()
        self._decision_semaphore = asyncio.Semaphore(
            self.config.max_inflight_ai_decisions
        )
        self.history_seed_counts: dict[str, int] = {}
        self.history_seed_errors: dict[str, str] = {}
        self.context_service_errors: dict[str, str] = {}
        self._latest_context_coverage: dict[str, Any] = {}
        self._latest_forecast_failures: list[dict[str, str]] = []
        self._write_status(None)

    async def run(
        self,
        *,
        max_ticks: int | None = None,
        max_ai_decisions: int | None = None,
    ) -> FreePublicAICouncilCounters:
        if max_ticks is not None and max_ticks <= 0:
            raise ValueError("max_ticks must be positive")
        if max_ai_decisions is not None and max_ai_decisions <= 0:
            raise ValueError("max_ai_decisions must be positive")

        try:
            await self._start_context_services()
            async for tick in self.feed.stream():
                self.counters.ticks += 1
                completed = self.aggregator.on_tick(tick)
                self.recorder.on_closed_candles(completed)
                opportunity_records = self.opportunity_auditor.on_closed_candles(
                    completed
                )
                triggers = self.online_bridge.observe_records(opportunity_records)
                self.counters.opportunity_outcomes_resolved += len(
                    opportunity_records
                )
                self.counters.research_triggers += len(triggers)
                self.counters.closed_candles += len(completed)
                for candle in completed:
                    key = (candle.symbol, candle.timeframe)
                    self._append_history(candle)
                    if candle.timeframe != self.config.decision_timeframe:
                        continue
                    self.bar_counts[key] += 1
                    if len(self.histories[key]) < self.config.min_history_bars:
                        continue
                    if self.bar_counts[key] % self.config.analyze_every_bars != 0:
                        continue
                    self._collect_finished()
                    if len(self._inflight) >= self.config.max_inflight_ai_decisions:
                        self.counters.skipped_ai_due_capacity += 1
                        continue
                    self._schedule_decision(candle)

                self._collect_finished()
                if max_ticks is not None and self.counters.ticks >= max_ticks:
                    self.feed.stop()
                    break
                if (
                    max_ai_decisions is not None
                    and self.counters.ai_decisions_started >= max_ai_decisions
                ):
                    self.feed.stop()
                    break
        finally:
            if self._inflight:
                await asyncio.gather(*tuple(self._inflight), return_exceptions=True)
                self._collect_finished()
            if self.config.enable_live_intelligence:
                await self.intelligence_service.stop()
            self._write_status(None)
        return self.counters

    def _schedule_decision(self, candle: NormalizedCandle) -> None:
        key = (candle.symbol, candle.timeframe)
        history = tuple(self.histories[key])
        context = AgentContext(
            correlation_id=(
                f"free-ai:{candle.venue}:{candle.symbol}:{candle.timeframe}:"
                f"{candle.close_time.isoformat()}"
            ),
            symbol=candle.symbol,
            decision_timeframe=candle.timeframe,
            candles=history,
            created_at=candle.close_time,
            metadata={
                "runtime": "free_public_multi_ai_council",
                "venue": candle.venue,
                "broker_credentials_present": False,
                "real_money_enabled": False,
            },
        )
        task = asyncio.create_task(self._analyze(context))
        self._inflight.add(task)
        self.counters.ai_decisions_started += 1

    async def _analyze(self, context: AgentContext) -> None:
        async with self._decision_semaphore:
            enriched = await self._enrich_context(context)
            result = await self.scanner.scan([enriched])
        self.recorder.register_scan(result)
        self.opportunity_auditor.register_scan(result)
        candidate = result.candidates[0]
        self.counters.ai_decisions_completed += 1
        if candidate.actionable:
            self.counters.actionable_decisions += 1
        self._write_status(candidate)

    def _collect_finished(self) -> None:
        finished = {task for task in self._inflight if task.done()}
        for task in finished:
            self._inflight.remove(task)
            exc = task.exception()
            if exc is not None:
                self._write_status(None, last_error=f"{type(exc).__name__}: {exc}")

    def _write_status(self, candidate, *, last_error: str | None = None) -> None:
        opportunity_metrics = self.opportunity_store.metrics()
        payload = {
            "mode": "NO_KEY_PUBLIC_LIVE_MULTI_AI_COUNCIL",
            "updated_at": datetime.now(UTC).isoformat(),
            "provider": self.config.provider,
            "symbols": list(self.config.symbols),
            "decision_timeframe": self.config.decision_timeframe,
            "deterministic_agent_count": len(self.team.agents) - self.ai_agent_count,
            "ai_agent_count": self.ai_agent_count,
            "real_money_enabled": False,
            "broker_orders_enabled": False,
            "reliability_provenance": SampleOrigin.LIVE_PUBLIC.value,
            "agent_reliability_observations": self.reliability_tracker.observation_count,
            "pending_shadow_outcomes": self.recorder.pending_count,
            "pending_opportunity_audits": self.opportunity_auditor.pending_count,
            "recovered_pending_opportunity_audits": (
                self.opportunity_auditor.recovered_pending_count
            ),
            "opportunity_pending_checkpoint": str(
                self.opportunity_auditor.pending_checkpoint_path
            ),
            "context_services": {
                "historical": {
                    "enabled": self.config.enable_public_history,
                    "seed_counts": dict(sorted(self.history_seed_counts.items())),
                    "errors": dict(sorted(self.history_seed_errors.items())),
                    "archive_dir": str(self.history_archive.root),
                },
                "intelligence": {
                    "enabled": self.config.enable_live_intelligence,
                    **self.intelligence_service.status(),
                },
                "forecast": {
                    "models": [
                        provider.model_key
                        for provider in self.forecast_service.providers
                    ],
                    "latest_failures": self._latest_forecast_failures,
                },
                "knowledge": {
                    "enabled": self.config.enable_local_knowledge,
                    "corpus_dir": str(self.config.knowledge_dir),
                    "indexed_chunks": len(self.knowledge_index.items),
                    "load_error": self.knowledge_load_error,
                    "ingest_errors": self.knowledge_ingest_errors[-20:],
                },
                "service_errors": dict(sorted(self.context_service_errors.items())),
                "latest_coverage": self._latest_context_coverage,
            },
            "opportunity_audit": {
                **asdict(opportunity_metrics),
                "capture_rate": opportunity_metrics.capture_rate,
            },
            "safe_online_learning": self.online_bridge.status(),
            "counters": {
                "ticks": self.counters.ticks,
                "closed_candles": self.counters.closed_candles,
                "ai_decisions_started": self.counters.ai_decisions_started,
                "ai_decisions_completed": self.counters.ai_decisions_completed,
                "actionable_decisions": self.counters.actionable_decisions,
                "skipped_ai_due_capacity": self.counters.skipped_ai_due_capacity,
                "opportunity_outcomes_resolved": (
                    self.counters.opportunity_outcomes_resolved
                ),
                "research_triggers": self.counters.research_triggers,
                "inflight": len(self._inflight),
            },
        }
        if last_error:
            payload["last_error"] = last_error
        if candidate is not None:
            payload["latest"] = {
                "correlation_id": candidate.context.correlation_id,
                "symbol": candidate.context.symbol,
                "timeframe": candidate.context.decision_timeframe,
                "intent": candidate.memo.intent.value,
                "confidence": candidate.memo.confidence,
                "quorum_met": candidate.memo.quorum_met,
                "actionable": candidate.actionable,
                "risk_flags": list(candidate.memo.risk_flags),
                "rationale": candidate.memo.rationale,
                "context_coverage": self._latest_context_coverage,
                "forecast_failures": self._latest_forecast_failures,
                "agent_evidence": [
                    {
                        "agent_id": evidence.agent_id,
                        "role": evidence.role.value,
                        "intent": evidence.intent.value,
                        "confidence": evidence.confidence,
                        "thesis": evidence.thesis,
                        "risk_flags": list(evidence.risk_flags),
                    }
                    for evidence in candidate.round.evidence
                ],
                "agent_failures": [
                    {
                        "agent_id": failure.agent_id,
                        "role": failure.role.value,
                        "error_type": failure.error_type,
                        "message": failure.message,
                    }
                    for failure in candidate.round.failures
                ],
            }
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.status_path)

    def _build_feed(self):
        if self.config.provider == "coinbase":
            return CoinbasePublicTradeFeed(self.config.symbols)
        return BybitPublicTradeFeed(self.config.symbols, market="spot")

    def _build_history_client(self) -> PublicHistoryClient:
        if self.config.provider == "coinbase":
            return CoinbaseExchangeHistoryClient()
        return BybitSpotHistoryClient()

    async def _start_context_services(self) -> None:
        tasks = []
        if self.config.enable_public_history:
            tasks.append(("historical", self._seed_historical_context()))
        if self.config.enable_live_intelligence:
            tasks.append(("intelligence", self.intelligence_service.start()))
        if not tasks:
            return
        results = await asyncio.gather(
            *(task for _, task in tasks),
            return_exceptions=True,
        )
        for (name, _), result in zip(tasks, results, strict=True):
            if isinstance(result, Exception):
                self.context_service_errors[name] = (
                    f"{type(result).__name__}: {result}"
                )
            else:
                self.context_service_errors.pop(name, None)
        self._write_status(None)

    async def _seed_historical_context(self) -> None:
        supported = self.history_client.supported_timeframes
        requests = [
            (symbol, timeframe)
            for symbol in self.config.symbols
            for timeframe in self.config.timeframes
            if timeframe in supported
        ]
        await asyncio.gather(
            *(self._seed_historical_series(symbol, timeframe) for symbol, timeframe in requests)
        )

    async def _seed_historical_series(self, symbol: str, timeframe: str) -> None:
        key = f"{symbol}:{timeframe}"
        try:
            archived = self.history_archive.read(symbol=symbol, timeframe=timeframe)
            for candle in archived[-self.config.history_seed_bars :]:
                self._append_history(candle)
        except Exception as exc:  # noqa: BLE001 - corrupted series is isolated
            self.history_seed_errors[key] = f"archive {type(exc).__name__}: {exc}"

        try:
            candles = await self.history_client.fetch_candles(
                symbol=symbol,
                timeframe=timeframe,
                limit=self.config.history_seed_bars,
            )
            self.history_archive.merge(candles)
            for candle in candles:
                self._append_history(candle)
            self.history_seed_counts[key] = len(self.histories[(symbol, timeframe)])
            self.history_seed_errors.pop(key, None)
        except Exception as exc:  # noqa: BLE001 - public provider failure is isolated
            self.history_seed_counts[key] = len(self.histories[(symbol, timeframe)])
            existing = self.history_seed_errors.get(key)
            provider_error = f"provider {type(exc).__name__}: {exc}"
            self.history_seed_errors[key] = (
                f"{existing}; {provider_error}" if existing else provider_error
            )

    def _append_history(self, candle: NormalizedCandle) -> None:
        history = self.histories[(candle.symbol, candle.timeframe)]
        if not history or candle.open_time > history[-1].open_time:
            history.append(candle)
            return
        if candle.open_time == history[-1].open_time:
            history[-1] = candle
            return
        merged = {item.open_time: item for item in history}
        merged[candle.open_time] = candle
        history.clear()
        history.extend(
            sorted(merged.values(), key=lambda item: item.open_time)[
                -self.config.max_history_bars :
            ]
        )

    async def _enrich_context(self, context: AgentContext) -> AgentContext:
        metadata = dict(context.metadata)
        htf_history = tuple(
            item
            for item in self.histories[(context.symbol, self.config.htf_timeframe)]
            if item.close_time <= context.created_at
        )
        if htf_history:
            metadata["htf_candles"] = [
                item.model_dump(mode="python") for item in htf_history
            ]

        cross_market = self._cross_market_observations(context)
        if cross_market:
            metadata["cross_market_observations"] = cross_market
            metadata["cross_market"] = cross_market

        intelligence_events: list[dict[str, Any]] = []
        if self.config.enable_live_intelligence:
            intelligence = self.intelligence_service.metadata_for(
                context.symbol,
                decision_time=context.created_at,
                limit=30,
            )
            intelligence_events = intelligence.get(
                "external_intelligence_events",
                [],
            )
            if intelligence_events:
                metadata["external_intelligence_events"] = intelligence_events
                metadata["live_intelligence"] = intelligence_events

        retrieved_knowledge = self.knowledge_index.search(
            (
                f"{context.symbol} trading market risk macro volatility forecast "
                "execution position sizing regime"
            ),
            as_of=context.created_at,
            limit=self.config.knowledge_limit,
        )
        if retrieved_knowledge:
            metadata["retrieved_knowledge"] = [
                {
                    "item_id": item.item_id,
                    "source_id": item.source_id,
                    "source_type": item.source_type.value,
                    "title": item.title,
                    "content": item.content,
                    "publication_date": item.publication_date.isoformat(),
                    "observed_at": item.observed_at.isoformat(),
                    "confidence": item.confidence,
                    "trust_score": item.trust_score,
                    "tags": list(item.tags),
                    "content_hash": item.content_hash,
                }
                for item in retrieved_knowledge
            ]

        forecast_round = await self.forecast_service.run(
            symbol=context.symbol,
            history=context.candles,
            horizon_steps=self.config.forecast_horizon_bars,
            as_of=context.created_at,
        )
        self._latest_forecast_failures = [
            item.model_dump(mode="json") for item in forecast_round.failures
        ]
        if forecast_round.ensemble is not None:
            metadata["forecast_ensemble"] = asdict(forecast_round.ensemble)

        coverage = {
            "symbol": context.symbol,
            "decision_candles": len(context.candles),
            "htf_timeframe": self.config.htf_timeframe,
            "htf_candles": len(htf_history),
            "cross_market_observations": len(cross_market),
            "intelligence_events": len(intelligence_events),
            "knowledge_chunks": len(retrieved_knowledge),
            "forecast_models": len(forecast_round.forecasts),
            "forecast_ensemble": forecast_round.ensemble is not None,
            "options_snapshot": "options_snapshot" in metadata,
            "execution_quality": "execution_quality" in metadata,
        }
        metadata["context_coverage"] = coverage
        self._latest_context_coverage = coverage
        return context.model_copy(update={"metadata": metadata})

    def _cross_market_observations(
        self,
        context: AgentContext,
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for related_symbol in self.config.symbols:
            if related_symbol == context.symbol:
                continue
            history = [
                item
                for item in self.histories[
                    (related_symbol, context.decision_timeframe)
                ]
                if item.close_time <= context.created_at
            ][-20:]
            if len(history) < 3:
                continue
            move = log(float(history[-1].close / history[0].close))
            if move > 0.0001:
                intent = SignalIntent.LONG
            elif move < -0.0001:
                intent = SignalIntent.SHORT
            else:
                intent = SignalIntent.FLAT
            observations.append(
                {
                    "source_id": (
                        f"market:{history[-1].venue}:{related_symbol}:"
                        f"{context.decision_timeframe}:observed-trend"
                    ),
                    "related_symbol": related_symbol,
                    "observed_at": history[-1].close_time,
                    "intent": intent.value,
                    "confidence": min(abs(move) * 25.0, 1.0),
                    "trust_score": 0.8,
                    "rationale": (
                        f"{related_symbol} moved {move * 100:.3f}% across "
                        f"{len(history) - 1} closed {context.decision_timeframe} intervals; "
                        "this is observed context, not a causal claim"
                    ),
                }
            )
        return observations
