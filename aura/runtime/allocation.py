from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aura.core.pipeline import DecisionPipeline, DecisionResult
from aura.domain.models import PortfolioSnapshot, StrategySignal
from aura.runtime.scanner import MarketScanResult, ScanCandidate


@dataclass(slots=True, frozen=True)
class CandidateAllocation:
    candidate: ScanCandidate
    decision: DecisionResult | None
    reserved_notional_after: Decimal


@dataclass(slots=True, frozen=True)
class PortfolioAllocationResult:
    allocations: tuple[CandidateAllocation, ...]
    reserved_gross_notional: Decimal

    @property
    def approved(self) -> tuple[CandidateAllocation, ...]:
        return tuple(
            allocation
            for allocation in self.allocations
            if allocation.decision is not None and allocation.decision.order is not None
        )


class PortfolioRiskCoordinator:
    """Serialize ranked opportunities through one portfolio risk/reservation authority.

    Intelligence scans may run concurrently, but approved yet-unfilled orders
    reserve gross exposure here before the next candidate is evaluated. Contract
    multipliers come from the same RiskEngine used for pre-trade sizing, so CFDs,
    futures and options cannot reserve only their quoted-price notional by mistake.
    """

    strategy_id = "aura.multi_market.ceo.v1"

    def __init__(
        self,
        decision_pipeline: DecisionPipeline,
        *,
        default_protective_stop_bps: Decimal | None = None,
    ) -> None:
        if default_protective_stop_bps is not None and default_protective_stop_bps <= 0:
            raise ValueError("default_protective_stop_bps must be positive")
        self.decision_pipeline = decision_pipeline
        self.default_protective_stop_bps = default_protective_stop_bps


    def _protective_stop_price(
        self,
        candidate: ScanCandidate,
        signal: StrategySignal,
    ) -> Decimal | None:
        if self.default_protective_stop_bps is None:
            return None
        stop_bps = self.default_protective_stop_bps
        quality = candidate.context.metadata.get("execution_quality")
        if isinstance(quality, dict):
            raw_broker_min = quality.get("broker_min_stop_bps")
            if raw_broker_min is not None:
                try:
                    broker_min = Decimal(str(raw_broker_min))
                except (ArithmeticError, ValueError):
                    broker_min = Decimal(0)
                if broker_min > stop_bps:
                    stop_bps = broker_min
        distance = signal.reference_price * stop_bps / Decimal(10000)
        if signal.intent.value == "LONG":
            return signal.reference_price - distance
        if signal.intent.value == "SHORT":
            return signal.reference_price + distance
        return None

    def allocate(
        self,
        scan: MarketScanResult,
        *,
        portfolio: PortfolioSnapshot,
        day_start_equity: Decimal,
        default_requested_quantity: Decimal,
        requested_quantities: dict[str, Decimal] | None = None,
        current_positions: dict[str, Decimal] | None = None,
    ) -> PortfolioAllocationResult:
        if default_requested_quantity <= 0:
            raise ValueError("default_requested_quantity must be positive")
        quantities = requested_quantities or {}
        positions = current_positions or {}
        reserved_gross = Decimal(0)
        allocations: list[CandidateAllocation] = []

        opportunities = sorted(
            scan.opportunities,
            key=lambda candidate: (
                -candidate.memo.confidence,
                candidate.context.symbol,
                candidate.context.decision_timeframe,
            ),
        )
        for candidate in opportunities:
            requested_quantity = quantities.get(
                candidate.context.correlation_id,
                default_requested_quantity,
            )
            if requested_quantity <= 0:
                raise ValueError("requested opportunity quantity must be positive")

            adjusted_portfolio = portfolio.model_copy(
                update={"gross_exposure": portfolio.gross_exposure + reserved_gross}
            )
            signal = StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candidate.context.symbol,
                intent=candidate.memo.intent,
                confidence=candidate.memo.confidence,
                reference_price=candidate.context.candles[-1].close,
                generated_at=candidate.context.created_at,
                reason=candidate.memo.rationale,
            )
            protective_stop_price = self._protective_stop_price(candidate, signal)
            decision = self.decision_pipeline.evaluate_signal(
                signal=signal,
                portfolio=adjusted_portfolio,
                day_start_equity=day_start_equity,
                venue=candidate.context.candles[-1].venue,
                requested_quantity=requested_quantity,
                current_position_quantity=positions.get(candidate.context.symbol, Decimal(0)),
                protective_stop_price=protective_stop_price,
            )
            if decision is not None and decision.order is not None:
                multiplier = self.decision_pipeline.risk_engine.notional_multiplier(
                    decision.order.symbol
                )
                reserved_gross += (
                    decision.order.quantity * signal.reference_price * multiplier
                )
            allocations.append(
                CandidateAllocation(
                    candidate=candidate,
                    decision=decision,
                    reserved_notional_after=reserved_gross,
                )
            )

        return PortfolioAllocationResult(
            allocations=tuple(allocations),
            reserved_gross_notional=reserved_gross,
        )
