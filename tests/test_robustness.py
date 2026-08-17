from __future__ import annotations

from aura.research.robustness import (
    RobustnessThresholds,
    WalkForwardPlan,
    bootstrap_monte_carlo,
    evaluate_robustness,
    summarize_walk_forward,
)


def test_walk_forward_splits_never_train_on_test_or_future_data() -> None:
    splits = WalkForwardPlan(train_size=10, test_size=4, step_size=4).splits(30)
    assert len(splits) == 5
    assert splits[0].train_start == 0
    assert splits[0].train_end == 10
    assert splits[0].test_start == 10
    assert splits[0].test_end == 14
    for split in splits:
        assert split.train_end == split.test_start
        assert split.train_end <= split.test_start
        assert split.train_size == 10
        assert split.test_size == 4


def test_expanding_walk_forward_keeps_past_and_never_uses_future() -> None:
    splits = WalkForwardPlan(
        train_size=8,
        test_size=2,
        step_size=2,
        expanding=True,
    ).splits(14)
    assert [split.train_start for split in splits] == [0, 0, 0]
    assert [split.train_end for split in splits] == [8, 10, 12]
    assert [split.test_start for split in splits] == [8, 10, 12]


def test_monte_carlo_is_deterministic_for_fixed_seed() -> None:
    returns = [0.01, -0.005, 0.02, 0.004, -0.003, 0.015, 0.006, -0.002]
    first = bootstrap_monte_carlo(returns, paths=500, block_size=2, seed=42)
    second = bootstrap_monte_carlo(returns, paths=500, block_size=2, seed=42)
    assert first == second
    assert 0 <= first.probability_of_loss <= 1
    assert first.p95_max_drawdown >= first.median_max_drawdown


def test_robustness_gate_approves_stable_positive_oos_profile() -> None:
    walk_forward = summarize_walk_forward([0.04, 0.03, 0.02, 0.05, 0.01])
    monte_carlo = bootstrap_monte_carlo(
        [0.01, 0.005, 0.008, -0.002, 0.012, 0.004, 0.006, -0.001],
        paths=500,
        block_size=2,
        seed=7,
    )
    decision = evaluate_robustness(
        walk_forward,
        monte_carlo,
        thresholds=RobustnessThresholds(
            min_positive_fold_ratio=0.8,
            min_compounded_oos_return=0.05,
            max_probability_of_loss=0.2,
            max_p95_drawdown=0.15,
        ),
    )
    assert decision.approved
    assert decision.reasons == ()


def test_robustness_gate_rejects_unstable_negative_profile() -> None:
    walk_forward = summarize_walk_forward([0.03, -0.08, -0.02, 0.01, -0.04])
    monte_carlo = bootstrap_monte_carlo(
        [-0.03, 0.01, -0.04, 0.005, -0.02, 0.015, -0.01],
        paths=500,
        block_size=2,
        seed=9,
    )
    decision = evaluate_robustness(
        walk_forward,
        monte_carlo,
        thresholds=RobustnessThresholds(
            min_positive_fold_ratio=0.6,
            min_compounded_oos_return=0.0,
            max_probability_of_loss=0.4,
            max_p95_drawdown=0.2,
        ),
    )
    assert not decision.approved
    assert len(decision.reasons) >= 2
