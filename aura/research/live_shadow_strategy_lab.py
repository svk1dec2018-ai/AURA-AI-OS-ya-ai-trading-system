from __future__ import annotations

import hashlib
import json
import math
import os
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.domain.models import NormalizedCandle, SignalIntent
from aura.evolution.core import StrategyGenome
from aura.research.autonomous_strategy_lab import AutonomousDslStrategy


@dataclass(slots=True, frozen=True)
class LiveShadowPolicy:
    horizon_bars: int = 5
    max_history_bars: int = 1200
    aspirational_win_rate: float = 0.80
    min_resolved_for_confidence: int = 500
    min_abs_outcome_bps: float = 0.5

    def __post_init__(self) -> None:
        if self.horizon_bars <= 0 or self.max_history_bars <= 0:
            raise ValueError("horizon/history settings must be positive")
        if not 0 < self.aspirational_win_rate < 1:
            raise ValueError("aspirational_win_rate must be in (0, 1)")
        if self.min_resolved_for_confidence <= 0:
            raise ValueError("min_resolved_for_confidence must be positive")
        if self.min_abs_outcome_bps < 0:
            raise ValueError("min_abs_outcome_bps cannot be negative")


@dataclass(slots=True, frozen=True)
class ShadowStrategyPlan:
    genome_id: str
    symbol: str
    timeframe: str
    decision_bar_index: int
    resolve_bar_index: int
    entry_price: Decimal
    intent: SignalIntent
    confidence: float


@dataclass(slots=True)
class _LiveMetric:
    resolved: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    sum_signed_return_bps: float = 0.0
    gross_positive_bps: float = 0.0
    gross_negative_bps: float = 0.0

    @property
    def win_rate(self) -> float:
        directional = self.wins + self.losses
        return self.wins / directional if directional else 0.0

    @property
    def expectancy_bps(self) -> float:
        return self.sum_signed_return_bps / self.resolved if self.resolved else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_negative_bps > 0:
            return self.gross_positive_bps / self.gross_negative_bps
        return 99.0 if self.gross_positive_bps > 0 else 0.0


@dataclass(slots=True, frozen=True)
class LiveStrategySnapshot:
    genome_id: str
    resolved: int
    wins: int
    losses: int
    flats: int
    win_rate: float
    expectancy_bps: float
    profit_factor: float
    score: float


class LiveShadowJournalHeader(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=1)
    record_type: Literal["header"] = "header"
    policy: dict[str, int | float]
    initial_genomes: tuple[StrategyGenome, ...]

    @model_validator(mode="after")
    def initial_population_must_be_unique(self) -> LiveShadowJournalHeader:
        _validate_population(self.initial_genomes, label="initial")
        return self


class LiveShadowCandleEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=1)
    record_type: Literal["candle"] = "candle"
    event_id: str = Field(min_length=1)
    candle: NormalizedCandle

    @field_validator("candle")
    @classmethod
    def candle_must_be_closed(cls, value: NormalizedCandle) -> NormalizedCandle:
        if not value.closed:
            raise ValueError("live shadow journal accepts only closed candles")
        return value

    @model_validator(mode="after")
    def event_id_matches_candle(self) -> LiveShadowCandleEvent:
        if self.event_id != _candle_event_id(self.candle):
            raise ValueError("live shadow candle event_id does not match its candle")
        return self


class LiveShadowPopulationEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=1)
    record_type: Literal["population"] = "population"
    event_id: str = Field(min_length=1)
    genomes: tuple[StrategyGenome, ...]
    preserve_retained_metrics: bool

    @model_validator(mode="after")
    def population_must_be_unique(self) -> LiveShadowPopulationEvent:
        _validate_population(self.genomes, label="replacement")
        return self


class LiveShadowStrategyLab:
    """Mass live-data strategy planning with zero execution authority.

    Every eligible closed research candle is evaluated by every candidate genome.
    Plans are resolved only after future bars arrive, creating forward-only live
    evidence. The lab can accumulate very large experience counts without sending
    any broker order or modifying the independent RiskEngine.
    """

    def __init__(
        self,
        genomes: tuple[StrategyGenome, ...] | list[StrategyGenome],
        *,
        policy: LiveShadowPolicy | None = None,
        journal_path: Path | None = None,
    ) -> None:
        if not genomes:
            raise ValueError("live shadow lab requires candidate genomes")
        unique = {item.genome_id: item for item in genomes}
        self.genomes = tuple(unique[key] for key in sorted(unique))
        self.policy = policy or LiveShadowPolicy()
        self._strategies = {
            item.genome_id: AutonomousDslStrategy(item) for item in self.genomes
        }
        self._histories: dict[tuple[str, str], deque[NormalizedCandle]] = defaultdict(
            lambda: deque(maxlen=self.policy.max_history_bars)
        )
        self._bar_index: dict[tuple[str, str], int] = defaultdict(int)
        self._pending: dict[tuple[str, str], list[ShadowStrategyPlan]] = defaultdict(list)
        self._metrics: dict[str, _LiveMetric] = {
            item.genome_id: _LiveMetric() for item in self.genomes
        }
        self.total_plans = 0
        self.total_resolved = 0
        self.discarded_pending_on_refresh = 0
        self.population_refreshes = 0
        self.processed_candles = 0
        self.total_strategies_seen = len(self.genomes)
        self.resolved_at_last_population_refresh = 0
        self.journal_path = journal_path
        self.recovered_events = 0
        self._journal_event_ids: set[str] = set()
        if self.journal_path is not None:
            self._initialize_or_replay_journal(tuple(unique.values()))

    def on_closed_candles(
        self,
        candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle],
    ) -> tuple[ShadowStrategyPlan, ...]:
        if any(not item.closed for item in candles):
            raise ValueError("live shadow lab accepts only closed candles")
        new_plans: list[ShadowStrategyPlan] = []
        for candle in sorted(candles, key=lambda item: (item.close_time, item.symbol, item.timeframe)):
            if self._is_idempotent_duplicate(candle):
                continue
            event = LiveShadowCandleEvent(
                event_id=_candle_event_id(candle),
                candle=candle,
            )
            self._append_journal_event(event)
            new_plans.extend(self._apply_candle(candle))
        return tuple(new_plans)

    def replace_population(
        self,
        genomes: tuple[StrategyGenome, ...] | list[StrategyGenome],
        *,
        preserve_retained_metrics: bool = True,
    ) -> None:
        """Install a new research population while preserving causal market history.

        Pending plans are discarded at refresh because removed candidates must not
        continue accumulating evidence. Retained genomes can keep their resolved
        metrics, while new challengers start with a clean score. Historical price
        context and per-series bar indices remain intact so challengers can begin
        evaluating immediately without replaying future information.
        """

        if not genomes:
            raise ValueError("replacement population cannot be empty")
        unique = {item.genome_id: item for item in genomes}
        ordered = tuple(unique[key] for key in sorted(unique))
        event = LiveShadowPopulationEvent(
            event_id=_population_event_id(self.population_refreshes + 1, ordered),
            genomes=ordered,
            preserve_retained_metrics=preserve_retained_metrics,
        )
        self._append_journal_event(event)
        self._apply_population(
            ordered,
            preserve_retained_metrics=preserve_retained_metrics,
        )

    def _apply_population(
        self,
        ordered: tuple[StrategyGenome, ...],
        *,
        preserve_retained_metrics: bool,
    ) -> None:
        previous_metrics = self._metrics
        previous_ids = set(previous_metrics)
        self.genomes = ordered
        self._strategies = {
            item.genome_id: AutonomousDslStrategy(item) for item in ordered
        }
        self._metrics = {
            item.genome_id: (
                previous_metrics[item.genome_id]
                if preserve_retained_metrics and item.genome_id in previous_metrics
                else _LiveMetric()
            )
            for item in ordered
        }
        discarded = self.pending_plans
        self.discarded_pending_on_refresh += discarded
        self._pending = defaultdict(list)
        self.population_refreshes += 1
        self.total_strategies_seen += len(set(self._metrics) - previous_ids)
        self.resolved_at_last_population_refresh = self.total_resolved

    def snapshots(self) -> tuple[LiveStrategySnapshot, ...]:
        result = []
        for genome in self.genomes:
            metric = self._metrics[genome.genome_id]
            result.append(
                LiveStrategySnapshot(
                    genome_id=genome.genome_id,
                    resolved=metric.resolved,
                    wins=metric.wins,
                    losses=metric.losses,
                    flats=metric.flats,
                    win_rate=metric.win_rate,
                    expectancy_bps=metric.expectancy_bps,
                    profit_factor=metric.profit_factor,
                    score=self._score(metric),
                )
            )
        result.sort(key=lambda item: item.score, reverse=True)
        return tuple(result)

    def top_genomes(self, limit: int = 8) -> tuple[StrategyGenome, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        by_id = {item.genome_id: item for item in self.genomes}
        return tuple(by_id[item.genome_id] for item in self.snapshots()[:limit])

    @property
    def pending_plans(self) -> int:
        return sum(len(items) for items in self._pending.values())

    def history_size(self, symbol: str, timeframe: str) -> int:
        return len(self._histories.get((symbol, timeframe), ()))

    def _apply_candle(self, candle: NormalizedCandle) -> tuple[ShadowStrategyPlan, ...]:
        key = (candle.symbol, candle.timeframe)
        history = self._histories[key]
        if history and candle.close_time <= history[-1].close_time:
            raise ValueError("live shadow history must be strictly increasing")
        self._bar_index[key] += 1
        index = self._bar_index[key]
        self._resolve(key, candle, index)
        history.append(candle)
        snapshot = tuple(history)
        new_plans: list[ShadowStrategyPlan] = []
        for genome_id, strategy in self._strategies.items():
            signal = strategy.on_closed_candle(snapshot)
            if signal is None or signal.intent == SignalIntent.FLAT:
                continue
            plan = ShadowStrategyPlan(
                genome_id=genome_id,
                symbol=candle.symbol,
                timeframe=candle.timeframe,
                decision_bar_index=index,
                resolve_bar_index=index + self.policy.horizon_bars,
                entry_price=candle.close,
                intent=signal.intent,
                confidence=signal.confidence,
            )
            self._pending[key].append(plan)
            new_plans.append(plan)
        self.total_plans += len(new_plans)
        self.processed_candles += 1
        return tuple(new_plans)

    def _is_idempotent_duplicate(self, candle: NormalizedCandle) -> bool:
        history = self._histories[(candle.symbol, candle.timeframe)]
        if not history or candle.close_time > history[-1].close_time:
            return False
        if candle.close_time == history[-1].close_time and candle == history[-1]:
            return True
        raise ValueError("live shadow history must be strictly increasing")

    def _initialize_or_replay_journal(
        self,
        supplied_genomes: tuple[StrategyGenome, ...],
    ) -> None:
        assert self.journal_path is not None
        path = self.journal_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            header = LiveShadowJournalHeader(
                policy=asdict(self.policy),
                initial_genomes=self.genomes,
            )
            self._append_line(header.model_dump_json())
            return

        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise RuntimeError(f"empty live shadow journal: {path}")
        try:
            header = LiveShadowJournalHeader.model_validate_json(lines[0])
        except Exception as exc:
            raise RuntimeError(f"invalid live shadow journal header {path}: {exc}") from exc
        if header.policy != asdict(self.policy):
            raise RuntimeError("live shadow policy changed for an existing journal")
        supplied_ids = {item.genome_id for item in supplied_genomes}
        initial_ids = {item.genome_id for item in header.initial_genomes}
        if supplied_ids != initial_ids:
            raise RuntimeError("initial live shadow population changed for an existing journal")

        self._install_initial_population(header.initial_genomes)
        for line_number, line in enumerate(lines[1:], start=2):
            try:
                raw = json.loads(line)
                record_type = raw.get("record_type") if isinstance(raw, dict) else None
                if record_type == "candle":
                    event = LiveShadowCandleEvent.model_validate(raw)
                elif record_type == "population":
                    event = LiveShadowPopulationEvent.model_validate(raw)
                else:
                    raise ValueError(f"unknown record_type: {record_type!r}")
            except Exception as exc:
                raise RuntimeError(
                    f"invalid live shadow journal record at line {line_number}: {exc}"
                ) from exc
            if event.event_id in self._journal_event_ids:
                raise RuntimeError(f"duplicate live shadow journal event: {event.event_id}")
            if isinstance(event, LiveShadowPopulationEvent) and event.event_id != (
                _population_event_id(self.population_refreshes + 1, event.genomes)
            ):
                raise RuntimeError(
                    f"invalid live shadow population sequence: {event.event_id}"
                )
            self._journal_event_ids.add(event.event_id)
            if isinstance(event, LiveShadowCandleEvent):
                self._apply_candle(event.candle)
            else:
                self._apply_population(
                    event.genomes,
                    preserve_retained_metrics=event.preserve_retained_metrics,
                )
            self.recovered_events += 1

    def _install_initial_population(
        self,
        genomes: tuple[StrategyGenome, ...],
    ) -> None:
        ordered = tuple(sorted(genomes, key=lambda item: item.genome_id))
        self.genomes = ordered
        self._strategies = {
            item.genome_id: AutonomousDslStrategy(item) for item in ordered
        }
        self._metrics = {item.genome_id: _LiveMetric() for item in ordered}
        self.total_strategies_seen = len(ordered)

    def _append_journal_event(
        self,
        event: LiveShadowCandleEvent | LiveShadowPopulationEvent,
    ) -> None:
        if self.journal_path is None:
            return
        if event.event_id in self._journal_event_ids:
            raise RuntimeError(f"duplicate live shadow journal event: {event.event_id}")
        self._append_line(event.model_dump_json())
        self._journal_event_ids.add(event.event_id)

    def _append_line(self, line: str) -> None:
        assert self.journal_path is not None
        created = not self.journal_path.exists()
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if created and os.name != "nt":
            directory_fd = os.open(self.journal_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def _resolve(
        self,
        key: tuple[str, str],
        candle: NormalizedCandle,
        current_index: int,
    ) -> None:
        pending = self._pending[key]
        if not pending:
            return
        keep: list[ShadowStrategyPlan] = []
        for plan in pending:
            if plan.resolve_bar_index > current_index:
                keep.append(plan)
                continue
            raw_return_bps = float((candle.close / plan.entry_price - Decimal(1)) * Decimal(10000))
            signed_return_bps = (
                raw_return_bps if plan.intent == SignalIntent.LONG else -raw_return_bps
            )
            metric = self._metrics.get(plan.genome_id)
            if metric is None:
                continue
            metric.resolved += 1
            metric.sum_signed_return_bps += signed_return_bps
            if abs(signed_return_bps) < self.policy.min_abs_outcome_bps:
                metric.flats += 1
            elif signed_return_bps > 0:
                metric.wins += 1
                metric.gross_positive_bps += signed_return_bps
            else:
                metric.losses += 1
                metric.gross_negative_bps += abs(signed_return_bps)
            self.total_resolved += 1
        self._pending[key] = keep

    def _score(self, metric: _LiveMetric) -> float:
        sample_strength = min(
            1.0,
            math.log1p(metric.resolved) / math.log1p(self.policy.min_resolved_for_confidence),
        )
        accuracy_progress = min(metric.win_rate / self.policy.aspirational_win_rate, 1.0)
        profit_factor_component = min(metric.profit_factor, 3.0) - 1.0
        return (
            4.0 * accuracy_progress * sample_strength
            + 0.20 * metric.expectancy_bps
            + profit_factor_component
            - 2.0 * (1.0 - sample_strength)
        )


def _candle_event_id(candle: NormalizedCandle) -> str:
    return f"candle:{candle.symbol}:{candle.timeframe}:{candle.close_time.isoformat()}"


def _population_event_id(
    refresh_number: int,
    genomes: tuple[StrategyGenome, ...],
) -> str:
    digest = hashlib.sha256(
        "|".join(item.content_hash for item in genomes).encode("utf-8")
    ).hexdigest()[:16]
    return f"population:{refresh_number}:{digest}"


def _validate_population(
    genomes: tuple[StrategyGenome, ...],
    *,
    label: str,
) -> None:
    if not genomes:
        raise ValueError(f"{label} live shadow population cannot be empty")
    ids = [item.genome_id for item in genomes]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} live shadow population contains duplicate genomes")
