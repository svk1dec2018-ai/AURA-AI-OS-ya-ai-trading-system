from pathlib import Path

import pytest

from aura.aura2.learning import PerformanceMemory, StrategyKey
from aura.aura2.mtf_consensus import (
    Direction,
    FrameSignal,
    MultiTimeframeConsensus,
    Timeframe,
)
from aura.aura2.opensource_registry import require_direct_copy_allowed
from aura.aura2.research_gateway import ResearchCandidate, ResearchGateway


def _signal(
    timeframe: Timeframe,
    direction: Direction,
    confidence: float = 0.8,
    trend: float = 0.7,
    volatility: float = 0.5,
) -> FrameSignal:
    return FrameSignal(timeframe, direction, confidence, trend, volatility)


def test_copyleft_projects_are_not_vendored_into_aura_core() -> None:
    assert require_direct_copy_allowed("qlib").name == "Microsoft Qlib"
    with pytest.raises(PermissionError):
        require_direct_copy_allowed("freqtrade")
    with pytest.raises(PermissionError):
        require_direct_copy_allowed("nexus")


def test_mtf_consensus_reads_execution_and_higher_timeframes() -> None:
    signals = [
        _signal(Timeframe.M1, Direction.BUY),
        _signal(Timeframe.M5, Direction.BUY),
        _signal(Timeframe.M15, Direction.BUY),
        _signal(Timeframe.M30, Direction.BUY),
        _signal(Timeframe.H1, Direction.BUY),
        _signal(Timeframe.H4, Direction.BUY),
        _signal(Timeframe.D1, Direction.BUY),
    ]
    result = MultiTimeframeConsensus().evaluate(signals)
    assert result.direction is Direction.BUY
    assert result.regime == "TREND"
    assert result.execution_alignment == 1.0
    assert result.higher_timeframe_alignment == 1.0
    assert result.tradeable()


def test_mtf_consensus_rejects_higher_timeframe_conflict() -> None:
    signals = [
        _signal(Timeframe.M1, Direction.BUY, confidence=0.95),
        _signal(Timeframe.M5, Direction.BUY, confidence=0.95),
        _signal(Timeframe.M15, Direction.BUY, confidence=0.95),
        _signal(Timeframe.H1, Direction.SELL, confidence=0.90),
        _signal(Timeframe.H4, Direction.SELL, confidence=0.90),
        _signal(Timeframe.D1, Direction.SELL, confidence=0.90),
    ]
    result = MultiTimeframeConsensus().evaluate(signals)
    assert result.direction is Direction.SELL
    assert result.execution_alignment == 0.0
    assert result.higher_timeframe_alignment == 1.0


def test_online_learning_is_bounded_and_restart_safe(tmp_path: Path) -> None:
    memory = PerformanceMemory()
    good = StrategyKey("XAUUSD", "trend_pullback", "trend", "london")
    weak = StrategyKey("XAUUSD", "mean_reversion", "trend", "london")
    for _ in range(80):
        memory.update(good, return_r=1.2, max_adverse_r=0.2)
        memory.update(weak, return_r=-0.7, max_adverse_r=0.9)
    assert memory.get(good).weight > memory.get(weak).weight
    assert 0.50 <= memory.get(good).weight <= 1.75
    path = tmp_path / "learning.json"
    memory.save(path)
    restored = PerformanceMemory.load(path)
    assert restored.get(good).trades == 80
    assert restored.get(good).weight == pytest.approx(memory.get(good).weight)


def test_external_research_never_gets_execution_or_risk_authority() -> None:
    candidate = ResearchCandidate(
        source="qlib",
        candidate_id="xau-trend-001",
        hypothesis="HTF trend plus M5 pullback",
        metrics={
            "trades": 600,
            "profit_factor": 1.55,
            "max_drawdown": 0.08,
            "expectancy_r": 0.18,
        },
        out_of_sample=True,
        walk_forward=True,
    )
    decision = ResearchGateway().ingest(candidate)
    assert decision.accepted_for_aura_validation is True
    assert decision.granted_execution_authority is False
    assert decision.granted_risk_authority is False
    assert decision.stage == "RESEARCH"


def test_weak_external_candidate_is_rejected() -> None:
    candidate = ResearchCandidate(
        source="finrl_x",
        candidate_id="rl-weak",
        hypothesis="RL allocator",
        metrics={
            "trades": 40,
            "profit_factor": 0.92,
            "max_drawdown": 0.31,
            "expectancy_r": -0.04,
        },
        out_of_sample=False,
        walk_forward=False,
    )
    decision = ResearchGateway().ingest(candidate)
    assert decision.accepted_for_aura_validation is False
    assert "insufficient_trades" in decision.reasons
    assert "missing_out_of_sample" in decision.reasons
