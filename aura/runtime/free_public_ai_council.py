from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aura.agents.models import AgentContext
from aura.agents.team import build_default_agent_team
from aura.data.candle_aggregation import SessionCandleAggregator
from aura.domain.models import NormalizedCandle
from aura.data.public_crypto_feeds import BybitPublicTradeFeed, CoinbasePublicTradeFeed
from aura.knowledge.firewall import KnowledgeFirewall
from aura.runtime.scanner import MultiMarketIntelligenceScanner


@dataclass(slots=True, frozen=True)
class FreePublicAICouncilConfig:
    provider: str = "coinbase"
    symbols: tuple[str, ...] = ("BTC-USD",)
    decision_timeframe: str = "1s"
    timeframes: tuple[str, ...] = ("1s", "5s", "15s", "30s", "1m")
    min_history_bars: int = 30
    analyze_every_bars: int = 5
    max_history_bars: int = 300
    max_inflight_ai_decisions: int = 2
    state_dir: Path = Path("runtime/free_public_ai_council")

    def __post_init__(self) -> None:
        if self.provider not in {"coinbase", "bybit"}:
            raise ValueError("provider must be coinbase or bybit")
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        if self.decision_timeframe not in self.timeframes:
            raise ValueError("decision_timeframe must be present in timeframes")
        if self.min_history_bars < 10:
            raise ValueError("min_history_bars must be at least 10")
        if self.analyze_every_bars <= 0 or self.max_history_bars < self.min_history_bars:
            raise ValueError("invalid analysis/history settings")
        if self.max_inflight_ai_decisions <= 0:
            raise ValueError("max_inflight_ai_decisions must be positive")


@dataclass(slots=True)
class FreePublicAICouncilCounters:
    ticks: int = 0
    closed_candles: int = 0
    ai_decisions_started: int = 0
    ai_decisions_completed: int = 0
    actionable_decisions: int = 0
    skipped_ai_due_capacity: int = 0


class FreePublicAICouncilRuntime:
    """No-key live public market data -> deterministic desk + local multi-AI council.

    Market ingestion keeps running while deep AI analyses execute in bounded
    background tasks. This runtime never creates or submits broker orders.
    """

    def __init__(self, config: FreePublicAICouncilConfig | None = None) -> None:
        self.config = config or FreePublicAICouncilConfig()
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        team = build_default_agent_team(KnowledgeFirewall(), include_env_ai=True)
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
        self.feed = self._build_feed()
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
            async for tick in self.feed.stream():
                self.counters.ticks += 1
                completed = self.aggregator.on_tick(tick)
                self.counters.closed_candles += len(completed)
                for candle in completed:
                    key = (candle.symbol, candle.timeframe)
                    self.histories[key].append(candle)
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
            result = await self.scanner.scan([context])
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
            "counters": {
                "ticks": self.counters.ticks,
                "closed_candles": self.counters.closed_candles,
                "ai_decisions_started": self.counters.ai_decisions_started,
                "ai_decisions_completed": self.counters.ai_decisions_completed,
                "actionable_decisions": self.counters.actionable_decisions,
                "skipped_ai_due_capacity": self.counters.skipped_ai_due_capacity,
                "inflight": len(self._inflight),
            },
        }
        if last_error:
            payload["last_error"] = last_error
        if candidate is not None:
            payload["latest"] = {
                "symbol": candidate.context.symbol,
                "timeframe": candidate.context.decision_timeframe,
                "intent": candidate.memo.intent.value,
                "confidence": candidate.memo.confidence,
                "quorum_met": candidate.memo.quorum_met,
                "actionable": candidate.actionable,
                "risk_flags": list(candidate.memo.risk_flags),
                "rationale": candidate.memo.rationale,
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
