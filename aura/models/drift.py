from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from aura.models.performance import ModelPerformanceSummary


class DriftDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    drifted: bool
    reasons: tuple[str, ...]
    reliability_drop: float = Field(ge=0.0)
    calibration_drop: float = Field(ge=0.0)
    hit_rate_drop: float = Field(ge=0.0)
    brier_increase: float = Field(ge=0.0)


@dataclass(slots=True, frozen=True)
class DriftThresholds:
    max_reliability_drop: float = 0.10
    max_calibration_drop: float = 0.10
    max_hit_rate_drop: float = 0.10
    max_brier_increase: float = 0.08
    min_reference_samples: int = 50
    min_recent_samples: int = 20

    def __post_init__(self) -> None:
        if any(
            value < 0
            for value in (
                self.max_reliability_drop,
                self.max_calibration_drop,
                self.max_hit_rate_drop,
                self.max_brier_increase,
            )
        ):
            raise ValueError("drift thresholds cannot be negative")
        if self.min_reference_samples <= 0 or self.min_recent_samples <= 0:
            raise ValueError("drift sample thresholds must be positive")


class ModelDriftDetector:
    def __init__(self, thresholds: DriftThresholds | None = None) -> None:
        self.thresholds = thresholds or DriftThresholds()

    def compare(
        self,
        reference: ModelPerformanceSummary,
        recent: ModelPerformanceSummary,
    ) -> DriftDecision:
        if (
            reference.model_key != recent.model_key
            or reference.task != recent.task
            or reference.market != recent.market
            or reference.regime != recent.regime
        ):
            raise ValueError("drift summaries must refer to the same model/task/market/regime")
        if reference.samples < self.thresholds.min_reference_samples:
            raise ValueError("reference performance window has insufficient samples")
        if recent.samples < self.thresholds.min_recent_samples:
            raise ValueError("recent performance window has insufficient samples")

        reliability_drop = max(0.0, reference.reliability_score - recent.reliability_score)
        calibration_drop = max(0.0, reference.calibration_score - recent.calibration_score)
        hit_rate_drop = max(0.0, reference.hit_rate - recent.hit_rate)
        brier_increase = max(0.0, recent.brier_score - reference.brier_score)
        reasons: list[str] = []
        checks = (
            (
                reliability_drop,
                self.thresholds.max_reliability_drop,
                "reliability drop",
            ),
            (
                calibration_drop,
                self.thresholds.max_calibration_drop,
                "calibration drop",
            ),
            (hit_rate_drop, self.thresholds.max_hit_rate_drop, "hit-rate drop"),
            (brier_increase, self.thresholds.max_brier_increase, "Brier-score increase"),
        )
        for actual, limit, label in checks:
            if actual > limit:
                reasons.append(f"{label} {actual:.4f} exceeds {limit:.4f}")
        return DriftDecision(
            drifted=bool(reasons),
            reasons=tuple(reasons),
            reliability_drop=reliability_drop,
            calibration_drop=calibration_drop,
            hit_rate_drop=hit_rate_drop,
            brier_increase=brier_increase,
        )


class PromotionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    promote_challenger: bool
    reasons: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ChampionChallengerPolicy:
    min_samples: int = 30
    min_reliability_improvement: float = 0.03
    min_calibration_improvement: float = 0.02
    max_brier_worsening: float = 0.0
    max_latency_ratio: float = 2.0

    def __post_init__(self) -> None:
        if self.min_samples <= 0:
            raise ValueError("champion/challenger min_samples must be positive")
        if self.max_latency_ratio <= 0:
            raise ValueError("max_latency_ratio must be positive")

    def evaluate(
        self,
        champion: ModelPerformanceSummary,
        challenger: ModelPerformanceSummary,
    ) -> PromotionDecision:
        if (
            champion.task != challenger.task
            or champion.market != challenger.market
            or champion.regime != challenger.regime
        ):
            raise ValueError("champion/challenger summaries must share task/market/regime")
        reasons: list[str] = []
        if challenger.samples < self.min_samples:
            reasons.append(f"challenger samples {challenger.samples} < {self.min_samples}")
        reliability_gain = challenger.reliability_score - champion.reliability_score
        if reliability_gain < self.min_reliability_improvement:
            reasons.append(
                f"reliability gain {reliability_gain:.4f} < {self.min_reliability_improvement:.4f}"
            )
        calibration_gain = challenger.calibration_score - champion.calibration_score
        if calibration_gain < self.min_calibration_improvement:
            reasons.append(
                f"calibration gain {calibration_gain:.4f} < {self.min_calibration_improvement:.4f}"
            )
        brier_worsening = challenger.brier_score - champion.brier_score
        if brier_worsening > self.max_brier_worsening:
            reasons.append(
                f"Brier worsening {brier_worsening:.4f} > {self.max_brier_worsening:.4f}"
            )
        # latency_score = 1/(1+latency_seconds); convert back to a monotonic ratio proxy.
        champion_latency = max((1.0 / max(champion.latency_score, 1e-12)) - 1.0, 1e-12)
        challenger_latency = max((1.0 / max(challenger.latency_score, 1e-12)) - 1.0, 1e-12)
        if challenger_latency / champion_latency > self.max_latency_ratio:
            reasons.append("challenger latency degradation exceeds policy")
        return PromotionDecision(promote_challenger=not reasons, reasons=tuple(reasons))
