from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field


class WalkForwardSplit(BaseModel):
    model_config = ConfigDict(frozen=True)

    fold: int = Field(ge=0)
    train_start: int = Field(ge=0)
    train_end: int = Field(gt=0)
    test_start: int = Field(ge=0)
    test_end: int = Field(gt=0)

    @property
    def train_size(self) -> int:
        return self.train_end - self.train_start

    @property
    def test_size(self) -> int:
        return self.test_end - self.test_start


@dataclass(slots=True, frozen=True)
class WalkForwardPlan:
    train_size: int
    test_size: int
    step_size: int | None = None
    expanding: bool = False

    def __post_init__(self) -> None:
        if self.train_size <= 0 or self.test_size <= 0:
            raise ValueError("walk-forward train/test sizes must be positive")
        if self.step_size is not None and self.step_size <= 0:
            raise ValueError("walk-forward step_size must be positive")

    def splits(self, data_length: int) -> tuple[WalkForwardSplit, ...]:
        if data_length < self.train_size + self.test_size:
            raise ValueError("not enough observations for one walk-forward fold")
        step = self.step_size or self.test_size
        result: list[WalkForwardSplit] = []
        anchor = self.train_size
        fold = 0
        while anchor + self.test_size <= data_length:
            train_start = 0 if self.expanding else anchor - self.train_size
            train_end = anchor
            test_start = anchor
            test_end = anchor + self.test_size
            result.append(
                WalkForwardSplit(
                    fold=fold,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
            fold += 1
            anchor += step
        return tuple(result)


class WalkForwardSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    folds: int = Field(gt=0)
    positive_fold_ratio: float = Field(ge=0.0, le=1.0)
    mean_fold_return: float
    median_fold_return: float
    worst_fold_return: float
    compounded_oos_return: float


def summarize_walk_forward(fold_returns: list[float] | tuple[float, ...]) -> WalkForwardSummary:
    if not fold_returns:
        raise ValueError("walk-forward summary requires at least one fold")
    values = [float(value) for value in fold_returns]
    if any(not math.isfinite(value) or value <= -1.0 for value in values):
        raise ValueError("walk-forward returns must be finite and greater than -100%")
    ordered = sorted(values)
    compounded = _compound(values)
    return WalkForwardSummary(
        folds=len(values),
        positive_fold_ratio=sum(value > 0 for value in values) / len(values),
        mean_fold_return=fmean(values),
        median_fold_return=_quantile(ordered, 0.5),
        worst_fold_return=min(values),
        compounded_oos_return=compounded,
    )


class MonteCarloSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    paths: int = Field(gt=0)
    observations_per_path: int = Field(gt=0)
    block_size: int = Field(gt=0)
    median_terminal_return: float
    p05_terminal_return: float
    p95_terminal_return: float
    probability_of_loss: float = Field(ge=0.0, le=1.0)
    median_max_drawdown: float = Field(ge=0.0)
    p95_max_drawdown: float = Field(ge=0.0)


def bootstrap_monte_carlo(
    returns: list[float] | tuple[float, ...],
    *,
    paths: int = 1000,
    block_size: int = 1,
    seed: int = 0,
) -> MonteCarloSummary:
    if paths <= 0:
        raise ValueError("Monte Carlo paths must be positive")
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    values = [float(value) for value in returns]
    if not values:
        raise ValueError("Monte Carlo requires at least one return")
    if block_size > len(values):
        raise ValueError("block_size cannot exceed available returns")
    if any(not math.isfinite(value) or value <= -1.0 for value in values):
        raise ValueError("returns must be finite and greater than -100%")

    rng = random.Random(seed)
    terminal_returns: list[float] = []
    max_drawdowns: list[float] = []
    for _ in range(paths):
        sampled = _sample_blocks(values, block_size=block_size, rng=rng)
        terminal_returns.append(_compound(sampled))
        max_drawdowns.append(_max_drawdown(sampled))

    terminal_returns.sort()
    max_drawdowns.sort()
    return MonteCarloSummary(
        paths=paths,
        observations_per_path=len(values),
        block_size=block_size,
        median_terminal_return=_quantile(terminal_returns, 0.5),
        p05_terminal_return=_quantile(terminal_returns, 0.05),
        p95_terminal_return=_quantile(terminal_returns, 0.95),
        probability_of_loss=sum(value < 0 for value in terminal_returns) / paths,
        median_max_drawdown=_quantile(max_drawdowns, 0.5),
        p95_max_drawdown=_quantile(max_drawdowns, 0.95),
    )


@dataclass(slots=True, frozen=True)
class RobustnessThresholds:
    min_positive_fold_ratio: float = 0.6
    min_compounded_oos_return: float = 0.0
    max_probability_of_loss: float = 0.4
    max_p95_drawdown: float = 0.25

    def __post_init__(self) -> None:
        for name, value in (
            ("min_positive_fold_ratio", self.min_positive_fold_ratio),
            ("max_probability_of_loss", self.max_probability_of_loss),
            ("max_p95_drawdown", self.max_p95_drawdown),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


class RobustnessDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved: bool
    reasons: tuple[str, ...]


def evaluate_robustness(
    walk_forward: WalkForwardSummary,
    monte_carlo: MonteCarloSummary,
    *,
    thresholds: RobustnessThresholds | None = None,
) -> RobustnessDecision:
    limits = thresholds or RobustnessThresholds()
    reasons: list[str] = []
    if walk_forward.positive_fold_ratio < limits.min_positive_fold_ratio:
        reasons.append(
            "walk-forward positive-fold ratio below threshold: "
            f"{walk_forward.positive_fold_ratio:.3f} < {limits.min_positive_fold_ratio:.3f}"
        )
    if walk_forward.compounded_oos_return <= limits.min_compounded_oos_return:
        reasons.append(
            "walk-forward compounded OOS return did not clear threshold: "
            f"{walk_forward.compounded_oos_return:.6f} <= {limits.min_compounded_oos_return:.6f}"
        )
    if monte_carlo.probability_of_loss > limits.max_probability_of_loss:
        reasons.append(
            "Monte Carlo probability of loss above threshold: "
            f"{monte_carlo.probability_of_loss:.3f} > {limits.max_probability_of_loss:.3f}"
        )
    if monte_carlo.p95_max_drawdown > limits.max_p95_drawdown:
        reasons.append(
            "Monte Carlo p95 drawdown above threshold: "
            f"{monte_carlo.p95_max_drawdown:.3f} > {limits.max_p95_drawdown:.3f}"
        )
    return RobustnessDecision(approved=not reasons, reasons=tuple(reasons))


def _sample_blocks(values: list[float], *, block_size: int, rng: random.Random) -> list[float]:
    sampled: list[float] = []
    max_start = len(values) - block_size
    while len(sampled) < len(values):
        start = rng.randint(0, max_start)
        sampled.extend(values[start : start + block_size])
    return sampled[: len(values)]


def _compound(returns: list[float] | tuple[float, ...]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1.0 + value
    return equity - 1.0


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown


def _quantile(ordered: list[float], probability: float) -> float:
    if not ordered:
        raise ValueError("quantile requires observations")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1")
    if len(ordered) == 1:
        return ordered[0]
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
