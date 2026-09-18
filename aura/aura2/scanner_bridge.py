from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol

from aura.agents.models import AgentContext
from aura.strategy.features import UnifiedFeatureEngine

from .feature_bridge import feature_snapshot_to_frame
from .mtf_consensus import FrameSignal, MultiTimeframeConsensus, Timeframe


class ScannerProtocol(Protocol):
    async def scan(self, contexts): ...


class AURA2MTFScanner:
    """Enrich AURA contexts with cached M1-D1 consensus before agent analysis.

    Closed-candle features are computed by AURA's existing UnifiedFeatureEngine.
    The cache stores advisory evidence only and grants no broker/risk authority.
    """

    def __init__(
        self,
        scanner: ScannerProtocol,
        *,
        feature_engine: UnifiedFeatureEngine | None = None,
    ) -> None:
        self.scanner = scanner
        self.feature_engine = feature_engine or UnifiedFeatureEngine()
        self.consensus_engine = MultiTimeframeConsensus()
        self._frames: dict[tuple[str, Timeframe], FrameSignal] = {}
        self._observed_at: dict[tuple[str, Timeframe], datetime] = {}
        self._latest_consensus: dict[str, dict[str, Any]] = {}

    def replace_scanner(self, scanner: ScannerProtocol) -> None:
        """Swap the policy-specific scanner while retaining MTF market memory."""
        self.scanner = scanner

    async def scan(
        self,
        contexts: list[AgentContext] | tuple[AgentContext, ...],
    ):
        prepared = tuple(contexts)
        self._observe(prepared)
        enriched = tuple(self._enrich(context) for context in prepared)
        return await self.scanner.scan(enriched)

    def _observe(self, contexts: Iterable[AgentContext]) -> None:
        for context in contexts:
            try:
                snapshot = self.feature_engine.compute(
                    context.candles,
                    decision_time=context.created_at,
                )
                frame = feature_snapshot_to_frame(snapshot)
            except (ArithmeticError, ValueError):
                continue
            observed_at = context.candles[-1].close_time
            key = (context.symbol, frame.timeframe)
            previous = self._observed_at.get(key)
            if previous is None or observed_at >= previous:
                self._frames[key] = frame
                self._observed_at[key] = observed_at

    def _enrich(self, context: AgentContext) -> AgentContext:
        available = [
            frame
            for (symbol, timeframe), frame in self._frames.items()
            if symbol == context.symbol
            and self._observed_at[(symbol, timeframe)] <= context.created_at
        ]
        if not available:
            return context

        consensus = self.consensus_engine.evaluate(available)
        timeframes = sorted(
            (frame.timeframe.value for frame in available),
            key=_timeframe_order,
        )
        payload = {
            "direction": consensus.direction.name,
            "directional_score": consensus.directional_score,
            "confidence": consensus.confidence,
            "agreement": consensus.agreement,
            "execution_alignment": consensus.execution_alignment,
            "higher_timeframe_alignment": consensus.higher_timeframe_alignment,
            "regime": consensus.regime,
            "timeframes": timeframes,
            "frame_count": len(available),
            "execution_authority": False,
            "risk_authority": False,
        }
        metadata = dict(context.metadata)
        metadata["aura2_mtf"] = payload
        self._latest_consensus[context.symbol] = payload
        return context.model_copy(update={"metadata": metadata})

    def status(self) -> dict[str, Any]:
        return {
            "symbols": len(self._latest_consensus),
            "cached_frames": len(self._frames),
            "latest": dict(self._latest_consensus),
            "execution_authority": False,
            "risk_authority": False,
        }


def _timeframe_order(value: str) -> int:
    order = {
        Timeframe.M1.value: 1,
        Timeframe.M5.value: 2,
        Timeframe.M15.value: 3,
        Timeframe.M30.value: 4,
        Timeframe.H1.value: 5,
        Timeframe.H4.value: 6,
        Timeframe.D1.value: 7,
    }
    return order[value]
