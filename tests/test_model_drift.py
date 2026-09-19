from aura.models.drift import ChampionChallengerPolicy, DriftThresholds, ModelDriftDetector
from aura.models.performance import ModelPerformanceSummary
from aura.models.registry import ModelTask


def _summary(
    model_key: str,
    *,
    samples: int,
    hit: float,
    brier: float,
    calibration: float,
    reliability: float,
    latency: float = 0.8,
) -> ModelPerformanceSummary:
    return ModelPerformanceSummary(
        model_key=model_key,
        task=ModelTask.MARKET_RESEARCH,
        market="XAUUSD",
        regime="trend",
        samples=samples,
        hit_rate=hit,
        brier_score=brier,
        calibration_score=calibration,
        reliability_score=reliability,
        latency_score=latency,
    )


def test_drift_detector_flags_recent_calibration_and_hit_rate_degradation() -> None:
    detector = ModelDriftDetector(
        DriftThresholds(
            max_reliability_drop=0.08,
            max_calibration_drop=0.08,
            max_hit_rate_drop=0.08,
            max_brier_increase=0.05,
            min_reference_samples=50,
            min_recent_samples=20,
        )
    )
    reference = _summary(
        "provider:model",
        samples=100,
        hit=0.75,
        brier=0.12,
        calibration=0.88,
        reliability=0.82,
    )
    recent = _summary(
        "provider:model",
        samples=30,
        hit=0.58,
        brier=0.25,
        calibration=0.72,
        reliability=0.65,
    )
    decision = detector.compare(reference, recent)
    assert decision.drifted
    assert decision.reliability_drop > 0.1
    assert decision.brier_increase > 0.1
    assert len(decision.reasons) >= 3


def test_stable_recent_window_is_not_drifted() -> None:
    reference = _summary(
        "provider:model",
        samples=100,
        hit=0.70,
        brier=0.15,
        calibration=0.85,
        reliability=0.78,
    )
    recent = _summary(
        "provider:model",
        samples=30,
        hit=0.69,
        brier=0.16,
        calibration=0.84,
        reliability=0.77,
    )
    assert not ModelDriftDetector().compare(reference, recent).drifted


def test_challenger_promotes_only_after_material_calibrated_improvement() -> None:
    champion = _summary(
        "provider:champion",
        samples=200,
        hit=0.65,
        brier=0.18,
        calibration=0.82,
        reliability=0.74,
    )
    challenger = _summary(
        "provider:challenger",
        samples=60,
        hit=0.72,
        brier=0.13,
        calibration=0.87,
        reliability=0.81,
    )
    decision = ChampionChallengerPolicy().evaluate(champion, challenger)
    assert decision.promote_challenger
    assert decision.reasons == ()


def test_challenger_with_too_few_samples_is_not_promoted() -> None:
    champion = _summary(
        "provider:champion",
        samples=200,
        hit=0.65,
        brier=0.18,
        calibration=0.82,
        reliability=0.74,
    )
    challenger = _summary(
        "provider:challenger",
        samples=10,
        hit=0.90,
        brier=0.05,
        calibration=0.95,
        reliability=0.90,
    )
    decision = ChampionChallengerPolicy(min_samples=30).evaluate(champion, challenger)
    assert not decision.promote_challenger
    assert "samples" in decision.reasons[0]
