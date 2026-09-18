"""AURA 2 open-source fusion layer.

This package is deliberately research/advisory only. It cannot bypass AURA's
independent risk, execution, reconciliation, or owner-approval boundaries.
"""

from .external_artifact import (
    ExternalResearchArtifact,
    ExternalResearchIntake,
    ExternalResearchMetrics,
)
from .learning import PerformanceMemory, StrategyKey
from .mtf_consensus import Direction, FrameSignal, MultiTimeframeConsensus, Timeframe
from .opensource_registry import PROJECTS, SourceProject
from .research_gateway import EvidenceGate, ResearchCandidate, ResearchGateway
from .sidecar import ResearchSidecarRunner, SidecarRequest, SidecarResult, SidecarSpec

__all__ = [
    "PROJECTS",
    "Direction",
    "EvidenceGate",
    "ExternalResearchArtifact",
    "ExternalResearchIntake",
    "ExternalResearchMetrics",
    "FrameSignal",
    "MultiTimeframeConsensus",
    "PerformanceMemory",
    "ResearchCandidate",
    "ResearchGateway",
    "ResearchSidecarRunner",
    "SidecarRequest",
    "SidecarResult",
    "SidecarSpec",
    "SourceProject",
    "StrategyKey",
    "Timeframe",
]
