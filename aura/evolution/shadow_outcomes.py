from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.agents.models import AgentEvidence, AgentRole
from aura.agents.reliability import AgentReliabilityTracker, reliability_market_key
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.evolution.brain_online import BrainReplayStore
from aura.evolution.brain_replay import BrainReplaySample, SampleOrigin
from aura.runtime.scanner import MarketScanResult, ScanCandidate


class ShadowOutcomePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon_bars: int = Field(default=5, ge=1)
    fallback_round_trip_cost_bps: float = Field(default=2.0, ge=0)


class PendingShadowDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(min_length=1)
    decision_time: datetime
    symbol: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    entry_price: Decimal = Field(gt=0)
    direction: SignalIntent
    regime: str = Field(min_length=1)
    memo_confidence: float = Field(ge=0, le=1)
    directional_margin: float = Field(ge=0, le=1)
    deliberation_disagreement: float = Field(ge=0, le=1)
    failed_agent_fraction: float = Field(ge=0, le=1)
    execution_spread_bps: float = Field(ge=0)
    estimated_slippage_bps: float = Field(ge=0)
    bars_seen: int = Field(default=0, ge=0)
    last_candle_close_time: datetime | None = None
    resolution_time: datetime | None = None
    resolution_price: Decimal | None = Field(default=None, gt=0)

    @field_validator("decision_time", "last_candle_close_time", "resolution_time")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("pending shadow timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def progress_is_consistent(self) -> PendingShadowDecision:
        _validate_pending_progress(
            decision_time=self.decision_time,
            bars_seen=self.bars_seen,
            last_candle_close_time=self.last_candle_close_time,
            resolution_time=self.resolution_time,
            resolution_price=self.resolution_price,
        )
        if self.direction not in {SignalIntent.LONG, SignalIntent.SHORT}:
            raise ValueError("pending shadow decision must be directional")
        return self


class PendingAgentOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_prefix: str = Field(min_length=1)
    decision_time: datetime
    symbol: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    market: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    entry_price: Decimal = Field(gt=0)
    round_trip_cost_bps: float = Field(ge=0)
    evidence: tuple[AgentEvidence, ...]
    bars_seen: int = Field(default=0, ge=0)
    last_candle_close_time: datetime | None = None
    resolution_time: datetime | None = None
    resolution_price: Decimal | None = Field(default=None, gt=0)

    @field_validator("decision_time", "last_candle_close_time", "resolution_time")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("pending agent timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def progress_is_consistent(self) -> PendingAgentOutcome:
        _validate_pending_progress(
            decision_time=self.decision_time,
            bars_seen=self.bars_seen,
            last_candle_close_time=self.last_candle_close_time,
            resolution_time=self.resolution_time,
            resolution_price=self.resolution_price,
        )
        if not self.evidence:
            raise ValueError("pending agent outcome requires directional evidence")
        if any(
            item.intent not in {SignalIntent.LONG, SignalIntent.SHORT}
            for item in self.evidence
        ):
            raise ValueError("pending agent evidence must be directional")
        return self


class ShadowOutcomePendingCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=1)
    policy: ShadowOutcomePolicy
    origin: SampleOrigin
    reliability_tracking_enabled: bool
    decisions: tuple[PendingShadowDecision, ...] = ()
    agent_outcomes: tuple[PendingAgentOutcome, ...] = ()


class ShadowDecisionOutcomeRecorder:
    """Resolve future outcomes for brain replay and every directional specialist.

    Brain replay samples remain restricted to safe directional CEO decisions.
    Separately, forward LIVE_PUBLIC/LIVE_BROKER runs score every directional agent
    opinion after the same causal horizon, including dissenting opinions when the
    CEO ultimately stayed FLAT or a downstream advisory policy rejected the trade.
    This lets AURA learn from missed opportunities without weakening safety gates.

    Pending causal horizons use an atomic checkpoint. Resolution data is checkpointed
    before append-only replay/reliability writes, so a crash can retry the exact same
    outcome idempotently instead of dropping it or substituting a later market bar.
    """

    def __init__(
        self,
        store: BrainReplayStore,
        *,
        policy: ShadowOutcomePolicy | None = None,
        origin: SampleOrigin = SampleOrigin.HISTORICAL,
        reliability_tracker: AgentReliabilityTracker | None = None,
        pending_checkpoint_path: Path | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or ShadowOutcomePolicy()
        self.origin = origin
        self.reliability_tracker = reliability_tracker
        self._known_sample_ids = {sample.sample_id for sample in store.read_all()}
        self.pending_checkpoint_path = pending_checkpoint_path or store.path.with_name(
            f"{store.path.stem}.pending.json"
        )
        self._pending, self._pending_agent_outcomes = self._load_pending()
        self.recovered_pending_count = len(self._pending)
        self.recovered_agent_outcome_count = len(self._pending_agent_outcomes)
        self._finalize_ready()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def pending_agent_outcome_count(self) -> int:
        return len(self._pending_agent_outcomes)

    def register_scan(self, scan: MarketScanResult) -> int:
        added = 0
        checkpoint_changed = False
        for candidate in scan.candidates:
            checkpoint_changed = self._register_agent_outcome(candidate) or checkpoint_changed
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
            self._pending[sample_id] = PendingShadowDecision(
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
            checkpoint_changed = True
        if checkpoint_changed:
            self._write_pending_checkpoint()
        return added

    def on_closed_candles(
        self,
        candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle],
    ) -> tuple[BrainReplaySample, ...]:
        if any(not candle.closed for candle in candles):
            raise ValueError("shadow outcomes require fully closed candles")
        resolved: list[BrainReplaySample] = []
        for candle in sorted(candles, key=lambda item: item.close_time):
            checkpoint_changed = self._advance_agent_outcomes(candle)
            matching_ids = [
                sample_id
                for sample_id, pending in self._pending.items()
                if pending.symbol == candle.symbol and pending.timeframe == candle.timeframe
            ]
            for sample_id in matching_ids:
                pending = self._pending[sample_id]
                if candle.close_time <= pending.decision_time:
                    continue
                if (
                    pending.last_candle_close_time is not None
                    and candle.close_time <= pending.last_candle_close_time
                ):
                    continue
                pending.bars_seen += 1
                pending.last_candle_close_time = candle.close_time
                checkpoint_changed = True
                if pending.bars_seen >= self.policy.horizon_bars:
                    pending.resolution_time = candle.close_time
                    pending.resolution_price = candle.close
            ready_pending = any(
                item.resolution_time is not None for item in self._pending.values()
            ) or any(
                item.resolution_time is not None
                for item in self._pending_agent_outcomes.values()
            )
            if checkpoint_changed or ready_pending:
                self._write_pending_checkpoint()
            resolved.extend(self._finalize_ready())
        return tuple(resolved)

    def _register_agent_outcome(self, candidate: ScanCandidate) -> bool:
        if self.reliability_tracker is None or self.origin not in {
            SampleOrigin.LIVE_BROKER,
            SampleOrigin.LIVE_PUBLIC,
        }:
            return False
        if candidate.data_quality is not None and not candidate.data_quality.safe_for_decision:
            return False
        directional = tuple(
            item
            for item in candidate.round.evidence
            if item.intent in {SignalIntent.LONG, SignalIntent.SHORT}
        )
        if not directional:
            return False
        latest = candidate.context.candles[-1]
        if latest.close <= 0:
            return False
        prefix = f"agent-reliability:{_sample_id(candidate)}"
        if prefix in self._pending_agent_outcomes:
            return False
        spread_bps, slippage_bps = _execution_cost_snapshot(candidate)
        round_trip_cost_bps = spread_bps + 2.0 * slippage_bps
        if round_trip_cost_bps <= 0:
            round_trip_cost_bps = self.policy.fallback_round_trip_cost_bps
        self._pending_agent_outcomes[prefix] = PendingAgentOutcome(
            observation_prefix=prefix,
            decision_time=candidate.context.created_at,
            symbol=candidate.context.symbol,
            timeframe=candidate.context.decision_timeframe,
            market=reliability_market_key(candidate.context),
            regime=_regime(candidate),
            entry_price=latest.close,
            round_trip_cost_bps=round_trip_cost_bps,
            evidence=directional,
        )
        return True

    def _advance_agent_outcomes(self, candle: NormalizedCandle) -> bool:
        changed = False
        matching = [
            key
            for key, pending in self._pending_agent_outcomes.items()
            if pending.symbol == candle.symbol and pending.timeframe == candle.timeframe
        ]
        for key in matching:
            pending = self._pending_agent_outcomes[key]
            if candle.close_time <= pending.decision_time:
                continue
            if (
                pending.last_candle_close_time is not None
                and candle.close_time <= pending.last_candle_close_time
            ):
                continue
            pending.bars_seen += 1
            pending.last_candle_close_time = candle.close_time
            changed = True
            if pending.bars_seen >= self.policy.horizon_bars:
                pending.resolution_time = candle.close_time
                pending.resolution_price = candle.close
        return changed

    def _record_agent_reliability(
        self,
        pending: PendingAgentOutcome,
        *,
        exit_price: Decimal,
        resolved_at: datetime,
    ) -> None:
        if self.reliability_tracker is None:
            return
        market_move_bps = float(
            (exit_price - pending.entry_price)
            / pending.entry_price
            * Decimal(10000)
        )
        if abs(market_move_bps) <= pending.round_trip_cost_bps:
            return
        realized_intent = (
            SignalIntent.LONG if market_move_bps > 0 else SignalIntent.SHORT
        )
        for evidence in pending.evidence:
            self.reliability_tracker.record_evidence_outcome(
                evidence,
                observation_prefix=pending.observation_prefix,
                market=pending.market,
                regime=pending.regime,
                realized_intent=realized_intent,
                decision_time=pending.decision_time,
                outcome_observed_at=resolved_at,
            )

    def _load_pending(
        self,
    ) -> tuple[dict[str, PendingShadowDecision], dict[str, PendingAgentOutcome]]:
        path = self.pending_checkpoint_path
        if not path.exists():
            return {}, {}
        try:
            checkpoint = ShadowOutcomePendingCheckpoint.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise RuntimeError(f"invalid shadow outcome checkpoint {path}: {exc}") from exc

        has_pending = bool(checkpoint.decisions or checkpoint.agent_outcomes)
        configuration_matches = (
            checkpoint.policy == self.policy
            and checkpoint.origin == self.origin
            and checkpoint.reliability_tracking_enabled
            == (self.reliability_tracker is not None)
        )
        if not configuration_matches:
            if has_pending:
                raise RuntimeError(
                    "shadow outcome configuration changed while unresolved records exist"
                )
            self._write_pending_checkpoint_for({}, {})
            return {}, {}

        decisions: dict[str, PendingShadowDecision] = {}
        decision_ids: set[str] = set()
        stale_checkpoint = False
        for item in checkpoint.decisions:
            if item.sample_id in decision_ids:
                raise RuntimeError(f"duplicate pending shadow sample: {item.sample_id}")
            decision_ids.add(item.sample_id)
            if item.sample_id in self._known_sample_ids:
                stale_checkpoint = True
                continue
            self._validate_checkpoint_progress(
                key=item.sample_id,
                bars_seen=item.bars_seen,
                resolution_time=item.resolution_time,
            )
            decisions[item.sample_id] = item

        agent_outcomes: dict[str, PendingAgentOutcome] = {}
        agent_keys: set[str] = set()
        for item in checkpoint.agent_outcomes:
            if item.observation_prefix in agent_keys:
                raise RuntimeError(
                    f"duplicate pending agent outcome: {item.observation_prefix}"
                )
            agent_keys.add(item.observation_prefix)
            self._validate_checkpoint_progress(
                key=item.observation_prefix,
                bars_seen=item.bars_seen,
                resolution_time=item.resolution_time,
            )
            agent_outcomes[item.observation_prefix] = item

        if stale_checkpoint:
            self._write_pending_checkpoint_for(decisions, agent_outcomes)
        return decisions, agent_outcomes

    def _validate_checkpoint_progress(
        self,
        *,
        key: str,
        bars_seen: int,
        resolution_time: datetime | None,
    ) -> None:
        if bars_seen > self.policy.horizon_bars:
            raise RuntimeError(f"pending shadow horizon overflow: {key}")
        ready = resolution_time is not None
        if ready != (bars_seen == self.policy.horizon_bars):
            raise RuntimeError(f"pending shadow resolution state is inconsistent: {key}")

    def _finalize_ready(self) -> tuple[BrainReplaySample, ...]:
        resolved: list[BrainReplaySample] = []
        checkpoint_changed = False

        for key in list(self._pending_agent_outcomes):
            pending = self._pending_agent_outcomes[key]
            if pending.resolution_time is None or pending.resolution_price is None:
                continue
            self._record_agent_reliability(
                pending,
                exit_price=pending.resolution_price,
                resolved_at=pending.resolution_time,
            )
            del self._pending_agent_outcomes[key]
            checkpoint_changed = True

        for sample_id in list(self._pending):
            pending = self._pending[sample_id]
            if pending.resolution_time is None or pending.resolution_price is None:
                continue
            sample = self._resolve(pending, pending.resolution_price)
            if self.store.append(sample):
                resolved.append(sample)
            self._known_sample_ids.add(sample.sample_id)
            del self._pending[sample_id]
            checkpoint_changed = True

        if checkpoint_changed:
            self._write_pending_checkpoint()
        return tuple(resolved)

    def _write_pending_checkpoint(self) -> None:
        self._write_pending_checkpoint_for(
            self._pending,
            self._pending_agent_outcomes,
        )

    def _write_pending_checkpoint_for(
        self,
        decisions: dict[str, PendingShadowDecision],
        agent_outcomes: dict[str, PendingAgentOutcome],
    ) -> None:
        checkpoint = ShadowOutcomePendingCheckpoint(
            policy=self.policy,
            origin=self.origin,
            reliability_tracking_enabled=self.reliability_tracker is not None,
            decisions=tuple(
                PendingShadowDecision.model_validate(item.model_dump())
                for _, item in sorted(decisions.items())
            ),
            agent_outcomes=tuple(
                PendingAgentOutcome.model_validate(item.model_dump())
                for _, item in sorted(agent_outcomes.items())
            ),
        )
        path = self.pending_checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(
                    checkpoint.model_dump(mode="json"),
                    handle,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            if os.name != "nt":
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def _resolve(
        self,
        pending: PendingShadowDecision,
        exit_price: Decimal,
    ) -> BrainReplaySample:
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


def _validate_pending_progress(
    *,
    decision_time: datetime,
    bars_seen: int,
    last_candle_close_time: datetime | None,
    resolution_time: datetime | None,
    resolution_price: Decimal | None,
) -> None:
    if (bars_seen == 0) != (last_candle_close_time is None):
        raise ValueError("pending shadow bar progress is inconsistent")
    if last_candle_close_time is not None and last_candle_close_time <= decision_time:
        raise ValueError("pending shadow progress must follow its decision")
    if (resolution_time is None) != (resolution_price is None):
        raise ValueError("pending shadow resolution is incomplete")
    if resolution_time is not None and resolution_time != last_candle_close_time:
        raise ValueError("pending shadow resolution must use the last counted candle")


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
                return value.lower()
    value = candidate.context.metadata.get("regime")
    return str(value).lower() if value else "unknown"
