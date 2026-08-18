from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aura.data.candle_aggregation import SessionCandleAggregator
from aura.data.public_crypto_feeds import CoinbasePublicTradeFeed, BybitPublicTradeFeed
from aura.evolution.core import EvolutionConfig, PopulationEvolution
from aura.research.autonomous_strategy_lab import autonomous_strategy_gene_specs
from aura.research.live_shadow_strategy_lab import LiveShadowPolicy, LiveShadowStrategyLab


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


@dataclass(slots=True)
class FreePublicStrategyLabCounters:
    ticks: int = 0
    closed_candles: int = 0
    generated_plans: int = 0


class FreePublicStrategyLabRuntime:
    """No-key live market-data research loop with zero execution authority."""

    def __init__(self, config: FreePublicStrategyLabConfig | None = None) -> None:
        self.config = config or FreePublicStrategyLabConfig()
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        evolution = PopulationEvolution(
            autonomous_strategy_gene_specs(),
            family="autonomous_strategy_dsl.v1",
            config=EvolutionConfig(
                population_size=self.config.population_size,
                elite_fraction=0.25,
                mutation_probability=0.70,
                crossover_probability=0.35,
                random_seed=20260818,
            ),
        )
        self.population = evolution.initial_population()
        self.lab = LiveShadowStrategyLab(
            self.population,
            policy=LiveShadowPolicy(
                horizon_bars=self.config.horizon_bars,
                max_history_bars=self.config.max_history_bars,
                aspirational_win_rate=self.config.aspirational_win_rate,
                min_resolved_for_confidence=self.config.min_resolved_for_confidence,
            ),
        )
        self.aggregator = SessionCandleAggregator(timeframes=self.config.timeframes)
        self.feed = self._build_feed()
        self.counters = FreePublicStrategyLabCounters()
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
            "aspirational_win_rate": self.config.aspirational_win_rate,
            "ticks": self.counters.ticks,
            "closed_candles": self.counters.closed_candles,
            "generated_plans": self.counters.generated_plans,
            "resolved_plans": self.lab.total_resolved,
            "pending_plans": self.lab.pending_plans,
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
            "live_approved": False,
            "research_only": True,
            "genomes": [by_id[item].model_dump(mode="json") for item in top_ids],
        }
        _atomic_json(self.top_genomes_path, payload)


def _atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
