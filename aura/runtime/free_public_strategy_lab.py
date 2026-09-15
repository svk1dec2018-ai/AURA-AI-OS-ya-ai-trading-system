from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aura.data.candle_aggregation import SessionCandleAggregator
from aura.data.public_crypto_feeds import BybitPublicTradeFeed, CoinbasePublicTradeFeed
from aura.evolution.core import EvolutionConfig, PopulationEvolution, StrategyGenome
from aura.research.autonomous_strategy_lab import autonomous_strategy_gene_specs
from aura.research.live_shadow_strategy_lab import LiveShadowPolicy, LiveShadowStrategyLab
from aura.research.strategy_mutation import StrategyMutationPolicy, mutate_autonomous_genome


@dataclass(slots=True, frozen=True)
class FreePublicStrategyLabConfig:
    provider: str = "coinbase"
    symbols: tuple[str, ...] = ("BTC-USD", "ETH-USD")
    timeframes: tuple[str, ...] = ("1s", "5s", "15s", "30s", "1m", "3m", "5m")
    population_size: int = 64
    horizon_bars: int = 5
    max_history_bars: int = 1200
    aspirational_win_rate: float = 0.80
    min_resolved_for_confidence: int = 500
    refresh_every_resolved_plans: int = 5000
    elite_fraction: float = 0.25
    mutation_probability: float = 0.65
    fresh_challenger_fraction: float = 0.10
    state_dir: Path = Path("runtime/free_public_strategy_lab")
    status_every_closed_candles: int = 100

    def __post_init__(self) -> None:
        if self.provider not in {"coinbase", "bybit"}:
            raise ValueError("provider must be coinbase or bybit")
        if not self.symbols or not self.timeframes:
            raise ValueError("symbols and timeframes are required")
        if self.population_size < 2:
            raise ValueError("population_size must be at least 2")
        if self.status_every_closed_candles <= 0:
            raise ValueError("status cadence must be positive")
        if self.refresh_every_resolved_plans <= 0:
            raise ValueError("refresh_every_resolved_plans must be positive")
        if not 0 < self.elite_fraction <= 0.5:
            raise ValueError("elite_fraction must be in (0, 0.5]")
        if not 0 < self.mutation_probability <= 1:
            raise ValueError("mutation_probability must be in (0, 1]")
        if not 0 <= self.fresh_challenger_fraction < 0.5:
            raise ValueError("fresh_challenger_fraction must be in [0, 0.5)")


@dataclass(slots=True)
class FreePublicStrategyLabCounters:
    ticks: int = 0
    closed_candles: int = 0
    generated_plans: int = 0
    population_refreshes: int = 0
    strategies_created: int = 0


class FreePublicStrategyLabRuntime:
    """No-key live market-data research loop with zero execution authority."""

    def __init__(
        self,
        config: FreePublicStrategyLabConfig | None = None,
        *,
        feed=None,
    ) -> None:
        self.config = config or FreePublicStrategyLabConfig()
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.evolution = PopulationEvolution(
            autonomous_strategy_gene_specs(),
            family="autonomous_strategy_dsl.v1",
            config=EvolutionConfig(
                population_size=self.config.population_size,
                elite_fraction=self.config.elite_fraction,
                mutation_probability=self.config.mutation_probability,
                crossover_probability=0.35,
                random_seed=20260818,
            ),
        )
        self.population = self.evolution.initial_population()
        self.lab = LiveShadowStrategyLab(
            self.population,
            policy=LiveShadowPolicy(
                horizon_bars=self.config.horizon_bars,
                max_history_bars=self.config.max_history_bars,
                aspirational_win_rate=self.config.aspirational_win_rate,
                min_resolved_for_confidence=self.config.min_resolved_for_confidence,
            ),
            journal_path=self.config.state_dir / "live_shadow_journal.jsonl",
        )
        self.population = self.lab.genomes
        self.aggregator = SessionCandleAggregator(timeframes=self.config.timeframes)
        self.feed = feed or self._build_feed()
        self.counters = FreePublicStrategyLabCounters(
            closed_candles=self.lab.processed_candles,
            generated_plans=self.lab.total_plans,
            population_refreshes=self.lab.population_refreshes,
            strategies_created=self.lab.total_strategies_seen,
        )
        self.population_generation = self.lab.population_refreshes
        self._resolved_at_last_refresh = self.lab.resolved_at_last_population_refresh
        self.status_path = self.config.state_dir / "status.json"
        self.top_genomes_path = self.config.state_dir / "top_research_seeds.json"

    async def run(
        self,
        *,
        max_ticks: int | None = None,
        max_closed_candles: int | None = None,
    ) -> FreePublicStrategyLabCounters:
        if max_ticks is not None and max_ticks <= 0:
            raise ValueError("max_ticks must be positive")
        if max_closed_candles is not None and max_closed_candles <= 0:
            raise ValueError("max_closed_candles must be positive")
        self._write_status()
        async for tick in self.feed.stream():
            self.counters.ticks += 1
            completed = self.aggregator.on_tick(tick)
            if completed:
                plans = self.lab.on_closed_candles(completed)
                self.counters.closed_candles += len(completed)
                self.counters.generated_plans += len(plans)
                self._maybe_refresh_population()
                if (
                    self.counters.closed_candles
                    % self.config.status_every_closed_candles
                    < len(completed)
                ):
                    self._write_status()
                    self._write_top_seeds()
            if max_ticks is not None and self.counters.ticks >= max_ticks:
                self.feed.stop()
                break
            if (
                max_closed_candles is not None
                and self.counters.closed_candles >= max_closed_candles
            ):
                self.feed.stop()
                break
        self._write_status()
        self._write_top_seeds()
        return self.counters

    def _maybe_refresh_population(self) -> None:
        new_resolved = self.lab.total_resolved - self._resolved_at_last_refresh
        if new_resolved < self.config.refresh_every_resolved_plans:
            return
        self.population_generation += 1
        elite_count = max(
            1,
            round(self.config.population_size * self.config.elite_fraction),
        )
        elites = list(self.lab.top_genomes(elite_count))
        new_population: list[StrategyGenome] = list(elites)
        existing_hashes = {item.content_hash for item in new_population}
        fresh_target = round(
            self.config.population_size * self.config.fresh_challenger_fraction
        )
        mutation_policy = StrategyMutationPolicy(
            mutation_probability=self.config.mutation_probability,
        )
        attempt = 0
        mutated_target = self.config.population_size - fresh_target
        while len(new_population) < mutated_target:
            parent = elites[attempt % len(elites)]
            child = mutate_autonomous_genome(
                parent,
                seed=(
                    20260818
                    + self.population_generation * 100_003
                    + attempt * 97
                ),
                policy=mutation_policy,
            )
            attempt += 1
            if child.content_hash in existing_hashes:
                if attempt > self.config.population_size * 100:
                    break
                continue
            existing_hashes.add(child.content_hash)
            new_population.append(child)

        random_attempts = 0
        while len(new_population) < self.config.population_size:
            random_attempts += 1
            candidate = self.evolution.random_genome(
                generation=self.population_generation,
            )
            if candidate.content_hash in existing_hashes:
                if random_attempts > self.config.population_size * 200:
                    raise RuntimeError("unable to create distinct live strategy population")
                continue
            existing_hashes.add(candidate.content_hash)
            new_population.append(candidate)

        self.population = tuple(new_population[: self.config.population_size])
        self.lab.replace_population(
            self.population,
            preserve_retained_metrics=True,
        )
        self._resolved_at_last_refresh = self.lab.total_resolved
        self.counters.population_refreshes += 1
        self.counters.strategies_created += self.config.population_size - len(elites)
        self._write_status()
        self._write_top_seeds()

    def _build_feed(self):
        if self.config.provider == "coinbase":
            return CoinbasePublicTradeFeed(self.config.symbols)
        return BybitPublicTradeFeed(self.config.symbols, market="spot")

    def _write_status(self) -> None:
        top = self.lab.snapshots()[:10]
        payload = {
            "mode": "NO_KEY_PUBLIC_LIVE_DATA_SHADOW_STRATEGY_LAB",
            "provider": self.config.provider,
            "symbols": list(self.config.symbols),
            "timeframes": list(self.config.timeframes),
            "population_size": len(self.population),
            "population_generation": self.population_generation,
            "population_refreshes": self.counters.population_refreshes,
            "strategies_created": self.counters.strategies_created,
            "aspirational_win_rate": self.config.aspirational_win_rate,
            "ticks": self.counters.ticks,
            "closed_candles": self.counters.closed_candles,
            "generated_plans": self.counters.generated_plans,
            "resolved_plans": self.lab.total_resolved,
            "pending_plans": self.lab.pending_plans,
            "discarded_pending_on_refresh": self.lab.discarded_pending_on_refresh,
            "journal_recovered_events": self.lab.recovered_events,
            "broker_credentials_required": False,
            "real_money_enabled": False,
            "paper_orders_enabled": False,
            "top_strategies": [
                {
                    "genome_id": item.genome_id,
                    "resolved": item.resolved,
                    "wins": item.wins,
                    "losses": item.losses,
                    "flats": item.flats,
                    "win_rate": item.win_rate,
                    "expectancy_bps": item.expectancy_bps,
                    "profit_factor": item.profit_factor,
                    "score": item.score,
                }
                for item in top
            ],
        }
        _atomic_json(self.status_path, payload)

    def _write_top_seeds(self) -> None:
        top_ids = [item.genome_id for item in self.lab.snapshots()[:16]]
        by_id = {item.genome_id: item for item in self.population}
        payload = {
            "source": "forward_public_live_shadow",
            "population_generation": self.population_generation,
            "live_approved": False,
            "research_only": True,
            "genomes": [by_id[item].model_dump(mode="json") for item in top_ids],
        }
        _atomic_json(self.top_genomes_path, payload)


def _atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
