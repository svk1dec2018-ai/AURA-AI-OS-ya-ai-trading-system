from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from aura.domain.models import SignalIntent
from aura.evolution.brain_online import (
    BrainPaperChampionManager,
    BrainPaperPromotionPolicy,
    BrainReplayStore,
)
from aura.evolution.brain_optimizer import BrainOptimizerConfig, BrainResearchOptimizer
from aura.evolution.brain_policy import (
    AuraBrainPolicy,
    BrainPolicyGate,
    build_brain_policy_team,
)
from aura.evolution.brain_replay import SampleOrigin
from aura.evolution.shadow_outcomes import (
    ShadowDecisionOutcomeRecorder,
    ShadowOutcomePolicy,
)
from aura.knowledge.firewall import KnowledgeFirewall
from aura.runtime.brain_scanner import BrainPolicyScanner
from aura.runtime.mt5_paper_daemon import (
    MT5AllMarketPaperConfig,
    MT5AllMarketPaperDaemon,
    build_mt5_all_market_paper_daemon,
)
from aura.runtime.scanner import MarketScanResult, MultiMarketIntelligenceScanner, ScanCandidate


class LearningBrainPolicyScanner(BrainPolicyScanner):
    """Brain-policy scanner that preserves the unfiltered round for learning."""

    def __init__(self, scanner: MultiMarketIntelligenceScanner, gate: BrainPolicyGate) -> None:
        super().__init__(scanner, gate)
        self.last_raw_scan = MarketScanResult(candidates=())

    async def scan(self, contexts) -> MarketScanResult:
        raw = await self.scanner.scan(contexts)
        self.last_raw_scan = raw
        candidates: list[ScanCandidate] = []
        for candidate in raw.candidates:
            decision = self.gate.evaluate(
                round_result=candidate.round,
                memo=candidate.memo,
                deliberation=candidate.deliberation,
            )
            if decision.allowed or candidate.memo.intent == SignalIntent.FLAT:
                candidates.append(candidate)
                continue
            memo = candidate.memo.model_copy(
                update={
                    "intent": SignalIntent.FLAT,
                    "confidence": 0.0,
                    "risk_flags": tuple(
                        dict.fromkeys(
                            (*candidate.memo.risk_flags, "brain_policy_block")
                        )
                    ),
                    "rationale": (
                        f"{candidate.memo.rationale}; brain policy blocked: "
                        f"{decision.reason}"
                    ),
                }
            )
            candidates.append(
                ScanCandidate(
                    context=candidate.context,
                    round=candidate.round,
                    memo=memo,
                    data_quality=candidate.data_quality,
                    agent_policy=candidate.agent_policy,
                    deliberation=candidate.deliberation,
                )
            )
        return MarketScanResult(candidates=tuple(candidates))


class MT5SelfEvolvingPaperDaemon:
    """Live MT5 data + internal paper execution + forward-only brain evolution."""

    def __init__(
        self,
        base: MT5AllMarketPaperDaemon,
        *,
        initial_policy: AuraBrainPolicy,
        optimizer: BrainResearchOptimizer,
        replay_store: BrainReplayStore,
        recorder: ShadowDecisionOutcomeRecorder,
        champion_manager: BrainPaperChampionManager,
        research_every_new_samples: int = 100,
    ) -> None:
        if research_every_new_samples <= 0:
            raise ValueError("research_every_new_samples must be positive")
        self.base = base
        self.current_policy = initial_policy
        self.optimizer = optimizer
        self.replay_store = replay_store
        self.recorder = recorder
        self.champion_manager = champion_manager
        self.research_every_new_samples = research_every_new_samples
        self._samples_at_last_research = len(self._live_samples())
        self.brain_state_dir = base.config.state_dir / "brain"
        self.brain_state_dir.mkdir(parents=True, exist_ok=True)
        self._install_policy(initial_policy)

    async def run(self, *, max_batches: int | None = None):
        if max_batches is not None and max_batches <= 0:
            raise ValueError("max_batches must be positive")
        await self.base.coordinator.start()
        self.base._write_status(None)
        try:
            async for batch in self.base.source.batches():
                resolved = self.recorder.on_closed_candles(batch)
                for sample in resolved:
                    self.champion_manager.observe(sample)
                if self.champion_manager.try_promote():
                    champion = self.champion_manager.paper_champion
                    assert champion is not None
                    self.current_policy = AuraBrainPolicy.from_genome(champion)
                    self._install_policy(self.current_policy)
                    self._write_brain_status("paper_champion_promoted")

                step = await self.base.coordinator.on_batch(batch)
                scanner = self.base.coordinator.scanner
                if not isinstance(scanner, LearningBrainPolicyScanner):
                    raise RuntimeError("learning daemon scanner was replaced unexpectedly")
                self.recorder.register_scan(scanner.last_raw_scan)

                self.base.counters.batches += 1
                self.base.counters.contexts += len(step.scan.candidates)
                self.base.counters.opportunities += len(step.scan.opportunities)
                self.base.counters.submitted_orders += len(step.submitted_orders)
                self.base.counters.fills += len(step.fills)
                if (
                    self.base.counters.batches
                    % self.base.config.reconcile_every_batches
                    == 0
                ):
                    self.base.coordinator.reconcile()
                    self.base.counters.reconciliations += 1

                self._maybe_research()
                self.base._write_status(step)
                self._write_brain_status("running")
                if max_batches is not None and self.base.counters.batches >= max_batches:
                    self.base.source.stop()
                    break
        finally:
            try:
                self.base.coordinator.reconcile()
                self.base.counters.reconciliations += 1
            finally:
                await self.base.coordinator.stop()
                self.base.gateway.shutdown()
                self.base._write_status(None)
                self._write_brain_status("stopped")
        return self.base.counters

    def _live_samples(self):
        return tuple(
            sample
            for sample in self.replay_store.read_all()
            if sample.origin == SampleOrigin.LIVE_BROKER
        )

    def _maybe_research(self) -> None:
        samples = self._live_samples()
        new_samples = len(samples) - self._samples_at_last_research
        if new_samples < self.research_every_new_samples:
            return
        if len(samples) < self.optimizer.config.minimum_samples:
            return
        if self.champion_manager.challenger is not None:
            return
        result = self.optimizer.optimize(samples, baseline=self.current_policy)
        self._samples_at_last_research = len(samples)
        self._write_research_result(result)
        if result.holdout_passed:
            self.champion_manager.install_research_challenger(
                result.genome,
                research_score=result.sealed_holdout.score,
            )

    def _install_policy(self, policy: AuraBrainPolicy) -> None:
        firewall = KnowledgeFirewall()
        team = build_brain_policy_team(firewall, policy)
        raw_scanner = MultiMarketIntelligenceScanner(
            orchestrator=team.orchestrator,
            ceo=team.ceo,
            agent_risk_policy=team.risk_policy,
            max_concurrent_contexts=self.base.config.max_concurrent_contexts,
        )
        self.base.coordinator.scanner = LearningBrainPolicyScanner(
            raw_scanner,
            BrainPolicyGate(policy),
        )

    def _write_research_result(self, result) -> None:
        payload = {
            "created_at": datetime.now(UTC).isoformat(),
            "genome": result.genome.model_dump(mode="json"),
            "genome_id": result.genome.genome_id,
            "validation": _metric_payload(result.validation),
            "sealed_holdout": _metric_payload(result.sealed_holdout),
            "holdout_passed": result.holdout_passed,
            "samples_used": result.samples_used,
            "sample_origin": SampleOrigin.LIVE_BROKER.value,
            "paper_validated": False,
            "live_approved": False,
        }
        _atomic_json(self.brain_state_dir / "latest_research_challenger.json", payload)

    def _write_brain_status(self, state: str) -> None:
        challenger = self.champion_manager.challenger
        metrics = self.champion_manager.challenger_metrics()
        all_samples = self.replay_store.read_all()
        live_samples = tuple(
            sample for sample in all_samples if sample.origin == SampleOrigin.LIVE_BROKER
        )
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "state": state,
            "current_paper_policy": self.current_policy.model_dump(),
            "current_paper_policy_genome_id": self.current_policy.to_genome().genome_id,
            "replay_samples": len(all_samples),
            "live_replay_samples": len(live_samples),
            "pending_shadow_outcomes": self.recorder.pending_count,
            "forward_challenger": (
                {
                    "genome_id": challenger.genome.genome_id,
                    "created_at": challenger.created_at.isoformat(),
                    "forward_samples": len(challenger.samples),
                    "metrics": _forward_metric_payload(metrics) if metrics else None,
                }
                if challenger is not None
                else None
            ),
            "validation_source_required": SampleOrigin.LIVE_BROKER.value,
            "real_money_enabled": False,
            "live_approved": False,
        }
        _atomic_json(self.brain_state_dir / "status.json", payload)


async def build_mt5_self_evolving_paper_daemon(
    config: MT5AllMarketPaperConfig | None = None,
    *,
    initial_policy: AuraBrainPolicy | None = None,
    optimizer_config: BrainOptimizerConfig | None = None,
    shadow_policy: ShadowOutcomePolicy | None = None,
    promotion_policy: BrainPaperPromotionPolicy | None = None,
    research_every_new_samples: int = 100,
) -> MT5SelfEvolvingPaperDaemon:
    base = await build_mt5_all_market_paper_daemon(config)
    brain_dir = base.config.state_dir / "brain"
    replay_store = BrainReplayStore(brain_dir / "replay_samples.jsonl")
    recorder = ShadowDecisionOutcomeRecorder(
        replay_store,
        policy=shadow_policy,
        origin=SampleOrigin.LIVE_BROKER,
    )
    manager = BrainPaperChampionManager(
        brain_dir,
        promotion_policy=promotion_policy,
    )
    restored_champion = manager.paper_champion
    effective_initial_policy = (
        AuraBrainPolicy.from_genome(restored_champion)
        if restored_champion is not None
        else initial_policy or AuraBrainPolicy()
    )
    return MT5SelfEvolvingPaperDaemon(
        base,
        initial_policy=effective_initial_policy,
        optimizer=BrainResearchOptimizer(optimizer_config),
        replay_store=replay_store,
        recorder=recorder,
        champion_manager=manager,
        research_every_new_samples=research_every_new_samples,
    )


def _metric_payload(metric) -> dict:
    return {
        "selected_trades": metric.selected_trades,
        "compounded_return_pct": metric.compounded_return_pct,
        "expectancy_pct": metric.expectancy_pct,
        "profit_factor": metric.profit_factor,
        "max_drawdown_pct": metric.max_drawdown_pct,
        "win_rate": metric.win_rate,
        "score": metric.score,
    }


def _forward_metric_payload(metric) -> dict:
    return {
        "trades": metric.trades,
        "compounded_return_pct": metric.compounded_return_pct,
        "expectancy_pct": metric.expectancy_pct,
        "profit_factor": metric.profit_factor,
        "max_drawdown_pct": metric.max_drawdown_pct,
        "win_rate": metric.win_rate,
    }


def _atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
