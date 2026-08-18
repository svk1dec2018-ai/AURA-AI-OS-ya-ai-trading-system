from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from aura.agents.models import AgentRole
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.evolution.brain_online import BrainReplayStore
from aura.evolution.brain_replay import BrainReplaySample, SampleOrigin
from aura.runtime.scanner import MarketScanResult, ScanCandidate


class ShadowOutcomePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon_bars: int = Field(default=5, ge=1)
    fallback_round_trip_cost_bps: float = Field(default=2.0, ge=0)


@dataclass(slots=True)
class _PendingDecision:
    sample_id: str
    decision_time: datetime
    symbol: str
    timeframe: str
    entry_price: Decimal
    direction: SignalIntent
    regime: str
    memo_confidence: float
    directional_margin: float
    deliberation_disagreement: float
    failed_agent_fraction: float
    execution_spread_bps: float
    estimated_slippage_bps: float
    bars_seen: int = 0


class ShadowDecisionOutcomeRecorder:
    """Resolve safe directional decisions against later closed bars.

    The recorder is intentionally independent from whether the evolvable brain
    accepted a trade. This lets AURA learn both taken and missed opportunities,
    while non-evolvable data/agent safety blocks remain excluded. Promotion
    provenance is explicit: only a live runtime should construct this recorder
    with `SampleOrigin.LIVE_BROKER`.
    """

    def __init__(
        self,
        store: BrainReplayStore,
        *,
        policy: ShadowOutcomePolicy | None = None,
        origin: SampleOrigin = SampleOrigin.HISTORICAL,
    ) -> None:
        self.store = store
        self.policy = policy or ShadowOutcomePolicy()
        self.origin = origin
        self._pending: dict[str, _PendingDecision] = {}
        self._known_sample_ids = {sample.sample_id for sample in store.read_all()}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def register_scan(self, scan: MarketScanResult) -> int:
        added = 0
        for candidate in scan.candidates:
            if not _eligible_for_shadow_learning(candidate):
                continue
            sample_id = _sample_id(candidate)
            if sample_id in self._pending or sample_id in self._known_sample_ids:
                continue
            latest = candidate.context.candles[-1]
            if latest.close <= 0:
                continue
            spread_bps, slippage_bps = _execution_cost_snapshot(candidate)
            total_agents = len(candidate.round.evidence) + len(candidate.round.failures)
            failed_fraction = (
                len(candidate.round.failures) / total_agents if total_agents else 1.0
            )
            self._pending[sample_id] = _PendingDecision(
                sample_id=sample_id,
                decision_time=candidate.context.created_at,
                symbol=candidate.context.symbol,
                timeframe=candidate.context.decision_timeframe,
                entry_price=latest.close,
                direction=candidate.memo.intent,
                regime=_regime(candidate),
                memo_confidence=candidate.memo.confidence,
                directional_margin=candidate.memo.confidence,
                deliberation_disagreement=(
                    candidate.deliberation.disagreement_ratio
                    if candidate.deliberation is not None
                    else 0.0
                ),
                failed_agent_fraction=failed_fraction,
                execution_spread_bps=spread_bps,
                estimated_slippage_bps=slippage_bps,
            )
            added += 1
        return added

    def on_closed_candles(
        self,
        candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle],
    ) -> tuple[BrainReplaySample, ...]:
        if any(not candle.closed for candle in candles):
            raise ValueError("shadow outcomes require fully closed candles")
        resolved: list[BrainReplaySample] = []
        for candle in sorted(candles, key=lambda item: item.close_time):
            matching_ids = [
                sample_id
                for sample_id, pending in self._pending.items()
                if pending.symbol == candle.symbol and pending.timeframe == candle.timeframe
            ]
            for sample_id in matching_ids:
                pending = self._pending[sample_id]
                if candle.close_time <= pending.decision_time:
                    continue
                pending.bars_seen += 1
                if pending.bars_seen < self.policy.horizon_bars:
                    continue
                sample = self._resolve(pending, candle.close)
                if self.store.append(sample):
                    self._known_sample_ids.add(sample.sample_id)
                    resolved.append(sample)
                del self._pending[sample_id]
        return tuple(resolved)

    def _resolve(self, pending: _PendingDecision, exit_price: Decimal) -> BrainReplaySample:
        if exit_price <= 0:
            raise ValueError("shadow exit price must be positive")
        raw_return = (exit_price - pending.entry_price) / pending.entry_price * Decimal(100)
        if pending.direction == SignalIntent.SHORT:
            raw_return = -raw_return
        round_trip_cost_bps = (
            pending.execution_spread_bps + 2.0 * pending.estimated_slippage_bps
        )
        if round_trip_cost_bps <= 0:
            round_trip_cost_bps = self.policy.fallback_round_trip_cost_bps
        net_return_pct = float(raw_return) - round_trip_cost_bps / 100.0
        return BrainReplaySample(
            sample_id=pending.sample_id,
            decision_time=pending.decision_time,
            symbol=pending.symbol,
            timeframe=pending.timeframe,
            regime=pending.regime,
            memo_confidence=pending.memo_confidence,
            directional_margin=pending.directional_margin,
            deliberation_disagreement=pending.deliberation_disagreement,
            failed_agent_fraction=pending.failed_agent_fraction,
            execution_spread_bps=pending.execution_spread_bps,
            estimated_slippage_bps=pending.estimated_slippage_bps,
            net_return_pct=net_return_pct,
            origin=self.origin,
        )


def _eligible_for_shadow_learning(candidate: ScanCandidate) -> bool:
    return (
        candidate.memo.quorum_met
        and candidate.memo.intent in {SignalIntent.LONG, SignalIntent.SHORT}
        and (candidate.agent_policy is None or candidate.agent_policy.allowed)
        and (candidate.data_quality is None or candidate.data_quality.safe_for_decision)
    )


def _sample_id(candidate: ScanCandidate) -> str:
    return f"shadow:{candidate.context.correlation_id}:{candidate.context.created_at.isoformat()}"


def _execution_cost_snapshot(candidate: ScanCandidate) -> tuple[float, float]:
    raw = candidate.context.metadata.get("execution_quality", {})
    if not isinstance(raw, dict):
        return 0.0, 0.0
    try:
        spread = max(0.0, float(raw.get("spread_bps", 0.0)))
        slippage = max(0.0, float(raw.get("estimated_slippage_bps", 0.0)))
    except (TypeError, ValueError):
        return 0.0, 0.0
    return spread, slippage


def _regime(candidate: ScanCandidate) -> str:
    for evidence in candidate.round.evidence:
        if evidence.role == AgentRole.REGIME:
            value = evidence.features.get("regime")
            if isinstance(value, str) and value:
                return value
    value = candidate.context.metadata.get("regime")
    return str(value) if value else "unknown"
