from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from aura.evolution.brain_replay import BrainReplaySample, SampleOrigin
from aura.evolution.core import StrategyGenome


class BrainPaperPromotionPolicy(BaseModel):
    """Minimum forward-live evidence required to replace a paper brain champion."""

    model_config = ConfigDict(frozen=True)

    min_forward_trades: int = Field(default=50, ge=10)
    min_expectancy_pct: float = 0.0
    min_profit_factor: float = Field(default=1.05, ge=1.0)
    max_drawdown_pct: float = Field(default=15.0, gt=0)
    require_positive_compounded_return: bool = True


class ForwardPaperMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    trades: int = Field(ge=0)
    compounded_return_pct: float
    expectancy_pct: float
    profit_factor: float = Field(ge=0)
    max_drawdown_pct: float = Field(ge=0)
    win_rate: float = Field(ge=0, le=1)


@dataclass(slots=True)
class ForwardBrainChallenger:
    genome: StrategyGenome
    research_score: float
    created_at: datetime
    samples: list[BrainReplaySample] = field(default_factory=list)


class BrainReplayStore:
    """Append-only local replay store for resolved decision outcomes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._known_ids = {sample.sample_id for sample in self.read_all()}

    def append(self, sample: BrainReplaySample) -> bool:
        if sample.sample_id in self._known_ids:
            return False
        line = sample.model_dump_json() + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self._known_ids.add(sample.sample_id)
        return True

    def read_all(self) -> tuple[BrainReplaySample, ...]:
        if not self.path.exists():
            return ()
        samples: list[BrainReplaySample] = []
        seen: set[str] = set()
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                sample = BrainReplaySample.model_validate_json(line)
            except Exception as exc:  # noqa: BLE001 - corrupt evolution state must fail closed
                raise RuntimeError(
                    f"invalid brain replay sample at line {line_number}: {exc}"
                ) from exc
            if sample.sample_id in seen:
                raise RuntimeError(f"duplicate brain replay sample_id: {sample.sample_id}")
            seen.add(sample.sample_id)
            samples.append(sample)
        return tuple(samples)


class BrainPaperChampionManager:
    """Forward-only champion/challenger gate using exclusively live broker samples.

    Historical or synthetic outcomes may help generate a research candidate, but
    they are never counted as forward paper validation. A promoted artifact is
    permanently marked as not live-approved and cannot enable real-money trading.
    """

    def __init__(
        self,
        state_dir: Path,
        *,
        promotion_policy: BrainPaperPromotionPolicy | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.promotion_policy = promotion_policy or BrainPaperPromotionPolicy()
        self._champion_path = self.state_dir / "brain_paper_champion.json"
        self._challenger_path = self.state_dir / "brain_forward_challenger.json"
        self._paper_champion = self._load_champion()
        self._challenger = self._load_challenger()

    @property
    def paper_champion(self) -> StrategyGenome | None:
        return self._paper_champion

    @property
    def challenger(self) -> ForwardBrainChallenger | None:
        return self._challenger

    def install_research_challenger(
        self,
        genome: StrategyGenome,
        *,
        research_score: float,
        created_at: datetime | None = None,
    ) -> None:
        timestamp = created_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("challenger created_at must be timezone-aware")
        if self._challenger is not None:
            raise RuntimeError("a forward brain challenger is already active")
        self._challenger = ForwardBrainChallenger(
            genome=genome,
            research_score=research_score,
            created_at=timestamp,
        )
        self._persist_challenger()

    def observe(self, sample: BrainReplaySample) -> bool:
        challenger = self._challenger
        if challenger is None:
            return False
        if sample.origin != SampleOrigin.LIVE_BROKER:
            return False
        if sample.decision_time <= challenger.created_at:
            return False
        if any(existing.sample_id == sample.sample_id for existing in challenger.samples):
            return False
        challenger.samples.append(sample)
        self._persist_challenger()
        return True

    def challenger_metrics(self) -> ForwardPaperMetrics | None:
        challenger = self._challenger
        if challenger is None or not challenger.samples:
            return None
        return _forward_metrics(challenger.samples)

    def try_promote(self) -> bool:
        challenger = self._challenger
        if challenger is None:
            return False
        if any(sample.origin != SampleOrigin.LIVE_BROKER for sample in challenger.samples):
            raise RuntimeError("non-live sample contaminated the forward challenger")
        metrics = self.challenger_metrics()
        if metrics is None:
            return False
        policy = self.promotion_policy
        passed = (
            metrics.trades >= policy.min_forward_trades
            and metrics.expectancy_pct > policy.min_expectancy_pct
            and metrics.profit_factor >= policy.min_profit_factor
            and metrics.max_drawdown_pct <= policy.max_drawdown_pct
            and (
                not policy.require_positive_compounded_return
                or metrics.compounded_return_pct > 0
            )
        )
        if not passed:
            return False

        promoted_at = datetime.now(UTC)
        payload = {
            "promoted_at": promoted_at.isoformat(),
            "genome": challenger.genome.model_dump(mode="json"),
            "genome_id": challenger.genome.genome_id,
            "research_score": challenger.research_score,
            "forward_metrics": metrics.model_dump(mode="json"),
            "forward_sample_ids": [sample.sample_id for sample in challenger.samples],
            "validation_source": SampleOrigin.LIVE_BROKER.value,
            "forward_only": True,
            "paper_validated": True,
            "live_approved": False,
            "live_money_enabled": False,
        }
        _atomic_json(self._champion_path, payload)
        self._paper_champion = challenger.genome
        self._challenger = None
        self._challenger_path.unlink(missing_ok=True)
        return True

    def _load_champion(self) -> StrategyGenome | None:
        if not self._champion_path.exists():
            return None
        payload = _read_json(self._champion_path)
        if payload.get("live_approved") is not False:
            raise RuntimeError("paper champion artifact has unsafe live_approved state")
        if payload.get("live_money_enabled") is not False:
            raise RuntimeError("paper champion artifact has unsafe live_money_enabled state")
        if payload.get("validation_source") != SampleOrigin.LIVE_BROKER.value:
            raise RuntimeError("paper champion lacks live broker validation provenance")
        return StrategyGenome.model_validate(payload["genome"])

    def _load_challenger(self) -> ForwardBrainChallenger | None:
        if not self._challenger_path.exists():
            return None
        payload = _read_json(self._challenger_path)
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise RuntimeError("persisted challenger has naive created_at")
        samples = [BrainReplaySample.model_validate(item) for item in payload.get("samples", [])]
        if any(sample.origin != SampleOrigin.LIVE_BROKER for sample in samples):
            raise RuntimeError("persisted challenger contains non-live validation samples")
        return ForwardBrainChallenger(
            genome=StrategyGenome.model_validate(payload["genome"]),
            research_score=float(payload["research_score"]),
            created_at=created_at,
            samples=samples,
        )

    def _persist_challenger(self) -> None:
        challenger = self._challenger
        if challenger is None:
            self._challenger_path.unlink(missing_ok=True)
            return
        _atomic_json(
            self._challenger_path,
            {
                "genome": challenger.genome.model_dump(mode="json"),
                "genome_id": challenger.genome.genome_id,
                "research_score": challenger.research_score,
                "created_at": challenger.created_at.isoformat(),
                "samples": [sample.model_dump(mode="json") for sample in challenger.samples],
                "validation_source_required": SampleOrigin.LIVE_BROKER.value,
                "live_approved": False,
                "live_money_enabled": False,
            },
        )


def _forward_metrics(samples: list[BrainReplaySample]) -> ForwardPaperMetrics:
    returns = [sample.net_return_pct for sample in samples]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    positives = [value for value in returns if value > 0]
    negatives = [value for value in returns if value < 0]
    for value in returns:
        equity *= max(0.0, 1.0 + value / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
    if negatives:
        profit_factor = sum(positives) / abs(sum(negatives))
    elif positives:
        profit_factor = 99.0
    else:
        profit_factor = 0.0
    return ForwardPaperMetrics(
        trades=len(returns),
        compounded_return_pct=(equity - 1.0) * 100.0,
        expectancy_pct=sum(returns) / len(returns),
        profit_factor=max(0.0, profit_factor),
        max_drawdown_pct=max_drawdown,
        win_rate=len(positives) / len(returns),
    )


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid evolution state file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"evolution state file is not an object: {path}")
    return payload


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
