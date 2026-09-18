"""AURA 2 open-source fusion layer.

This package is deliberately research/advisory only. It cannot bypass AURA's
independent risk, execution, reconciliation, or owner-approval boundaries.
"""

from .learning import PerformanceMemory, StrategyKey
from .mtf_consensus import Direction, FrameSignal, MultiTimeframeConsensus, Timeframe
from .opensource_registry import PROJECTS, SourceProject
from .research_gateway import EvidenceGate, ResearchCandidate, ResearchGateway

__all__ = [
    "Direction",
    "EvidenceGate",
    "FrameSignal",
    "MultiTimeframeConsensus",
    "PROJECTS",
    "PerformanceMemory",
    "ResearchCandidate",
    "ResearchGateway",
    "SourceProject",
    "StrategyKey",
    "Timeframe",
]
