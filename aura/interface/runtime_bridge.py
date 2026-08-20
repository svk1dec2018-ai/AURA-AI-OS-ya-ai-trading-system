from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from aura.interface.operator_read_model import OperatorReadModel, ReadDomain
from aura.risk.engine import RiskEngine
from aura.runtime.multi_market_paper import MultiMarketPaperStep
from aura.runtime.opportunity_radar import OpportunityRadar
from aura.runtime.scanner import MarketScanResult, ScanCandidate


@dataclass(frozen=True, slots=True)
class RuntimeBridgeFreshness:
    opportunities: timedelta = timedelta(minutes=2)
    portfolio: timedelta = timedelta(minutes=2)
    risk: timedelta = timedelta(minutes=2)
    agents: timedelta = timedelta(minutes=2)
    data: timedelta = timedelta(minutes=2)
    brokers: timedelta = timedelta(minutes=2)
    system: timedelta = timedelta(minutes=2)

    def __post_init__(self) -> None:
        if any(
            value <= timedelta(0)
            for value in (
                self.opportunities,
                self.portfolio,
                self.risk,
                self.agents,
                self.data,
                self.brokers,
                self.system,
            )
        ):
            raise ValueError("runtime bridge freshness windows must be positive")


class OperatorRuntimeBridge:
    """Publish immutable governed runtime snapshots into the owner read model.

    The bridge is intentionally one-way. It has no broker submit/cancel methods
    and cannot send UI commands back into a trading coordinator. It only converts
    already-produced scanner/paper state into finite JSON snapshots with source
    provenance and freshness windows.
    """

    def __init__(
        self,
        read_model: OperatorReadModel,
        *,
        radar: OpportunityRadar | None = None,
        freshness: RuntimeBridgeFreshness | None = None,
    ) -> None:
        self.read_model = read_model
        self.radar = radar or OpportunityRadar()
        self.freshness = freshness or RuntimeBridgeFreshness()

    def publish_scan(
        self,
        scan: MarketScanResult,
        *,
        source: str,
        observed_at: datetime | None = None,
        runtime_metadata: dict[str, Any] | None = None,
        received_at: datetime | None = None,
    ) -> None:
        if not source.strip():
            raise ValueError("scan source is required")
        evaluation_time = observed_at or _scan_time(scan)
        if evaluation_time is None:
            raise ValueError("cannot publish an empty scan without observed_at")
        received = received_at or datetime.now(UTC)

        radar_snapshot = self.radar.rank(scan)
        if radar_snapshot.as_of is not None:
            self.read_model.publish_opportunity_radar(
                radar_snapshot,
                source=f"{source}:opportunity-radar",
                max_age=self.freshness.opportunities,
                received_at=received,
            )

        self.read_model.publish(
            ReadDomain.AGENTS,
            _agent_payload(scan),
            source=f"{source}:agents",
            observed_at=evaluation_time,
            max_age=self.freshness.agents,
            received_at=received,
        )
        self.read_model.publish(
            ReadDomain.DATA,
            _data_payload(scan),
            source=f"{source}:data",
            observed_at=evaluation_time,
            max_age=self.freshness.data,
            received_at=received,
        )
        system_payload: dict[str, Any] = {
            "mode": "observation_only",
            "live_money_enabled": False,
            "broker_order_authority": False,
            "candidate_count": len(scan.candidates),
            "actionable_count": len(scan.opportunities),
        }
        if runtime_metadata:
            system_payload["runtime"] = runtime_metadata
        self.read_model.publish(
            ReadDomain.SYSTEM,
            system_payload,
            source=f"{source}:system",
            observed_at=evaluation_time,
            max_age=self.freshness.system,
            received_at=received,
        )

    def publish_paper_step(
        self,
        step: MultiMarketPaperStep,
        *,
        risk_engine: RiskEngine,
        day_start_equity: Decimal,
        broker_name: str = "AURA_PAPER",
        broker_connected: bool = True,
        source: str = "multi-market-paper",
        received_at: datetime | None = None,
    ) -> None:
        if day_start_equity <= 0:
            raise ValueError("day_start_equity must be positive")
        observed_at = _scan_time(step.scan) or _parse_iso(step.close_time_iso)
        received = received_at or datetime.now(UTC)
        self.publish_scan(
            step.scan,
            source=source,
            observed_at=observed_at,
            runtime_metadata={
                "execution_mode": "PAPER",
                "fills": len(step.fills),
                "submitted_paper_orders": len(step.submitted_orders),
                "allocations": len(step.allocation.allocations),
                "approved_allocations": len(step.allocation.approved),
            },
            received_at=received,
        )

        self.read_model.publish(
            ReadDomain.PORTFOLIO,
            _portfolio_payload(step),
            source=f"{source}:portfolio-ledger",
            observed_at=observed_at,
            max_age=self.freshness.portfolio,
            received_at=received,
        )
        self.read_model.publish(
            ReadDomain.RISK,
            _risk_payload(risk_engine, step, day_start_equity=day_start_equity),
            source=f"{source}:risk-engine",
            observed_at=observed_at,
            max_age=self.freshness.risk,
            received_at=received,
        )
        self.read_model.publish(
            ReadDomain.BROKERS,
            {
                "broker": broker_name,
                "connected": broker_connected,
                "execution_mode": "PAPER",
                "live_money_enabled": False,
                "submitted_paper_orders": len(step.submitted_orders),
                "fills_this_step": len(step.fills),
            },
            source=f"{source}:broker-status",
            observed_at=observed_at,
            max_age=self.freshness.brokers,
            received_at=received,
        )


def _scan_time(scan: MarketScanResult) -> datetime | None:
    if not scan.candidates:
        return None
    return max(candidate.context.created_at for candidate in scan.candidates)


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("paper step close time must be timezone-aware")
    return parsed


def _agent_payload(scan: MarketScanResult) -> dict[str, Any]:
    return {
        "candidate_count": len(scan.candidates),
        "candidates": [_candidate_agents(candidate) for candidate in scan.candidates],
    }


def _candidate_agents(candidate: ScanCandidate) -> dict[str, Any]:
    return {
        "correlation_id": candidate.context.correlation_id,
        "symbol": candidate.context.symbol,
        "timeframe": candidate.context.decision_timeframe,
        "ceo": {
            "intent": candidate.memo.intent.value,
            "confidence": candidate.memo.confidence,
            "quorum_met": candidate.memo.quorum_met,
            "supporting_agents": list(candidate.memo.supporting_agents),
            "opposing_agents": list(candidate.memo.opposing_agents),
            "abstaining_agents": list(candidate.memo.abstaining_agents),
            "risk_flags": list(candidate.memo.risk_flags),
            "rationale": candidate.memo.rationale,
        },
        "evidence": [
            {
                "agent_id": item.agent_id,
                "role": item.role.value,
                "intent": item.intent.value,
                "confidence": item.confidence,
                "thesis": item.thesis,
                "risk_flags": list(item.risk_flags),
                "source_ids": [source.source_id for source in item.sources],
            }
            for item in candidate.round.evidence
        ],
        "failures": [
            {
                "agent_id": failure.agent_id,
                "role": failure.role.value,
                "error_type": failure.error_type,
                "message": failure.message,
            }
            for failure in candidate.round.failures
        ],
    }


def _data_payload(scan: MarketScanResult) -> dict[str, Any]:
    series: list[dict[str, Any]] = []
    for candidate in scan.candidates:
        latest = candidate.context.candles[-1]
        quality = candidate.data_quality
        series.append(
            {
                "symbol": candidate.context.symbol,
                "venue": latest.venue,
                "timeframe": latest.timeframe,
                "close_time": latest.close_time.isoformat(),
                "closed": latest.closed,
                "bars": len(candidate.context.candles),
                "quality": None
                if quality is None
                else {
                    "safe_for_decision": quality.safe_for_decision,
                    "bars_checked": quality.bars_checked,
                    "issues": [
                        {
                            "type": issue.issue_type.value,
                            "severity": issue.severity.value,
                            "detail": issue.detail,
                        }
                        for issue in quality.issues
                    ],
                },
            }
        )
    return {"series": series}


def _portfolio_payload(step: MultiMarketPaperStep) -> dict[str, Any]:
    portfolio = step.portfolio
    return {
        "cash": str(portfolio.cash),
        "equity": str(portfolio.equity),
        "gross_exposure": str(portfolio.gross_exposure),
        "net_exposure": str(portfolio.net_exposure),
        "realized_pnl": str(portfolio.realized_pnl),
        "unrealized_pnl": str(portfolio.unrealized_pnl),
        "peak_equity": str(portfolio.peak_equity),
        "drawdown_pct": str(portfolio.drawdown_pct),
        "position_values": {
            symbol: str(value) for symbol, value in sorted(portfolio.position_values.items())
        },
        "fills_this_step": len(step.fills),
        "submitted_paper_orders": len(step.submitted_orders),
    }


def _risk_payload(
    risk_engine: RiskEngine,
    step: MultiMarketPaperStep,
    *,
    day_start_equity: Decimal,
) -> dict[str, Any]:
    portfolio = step.portfolio
    daily_loss_pct = Decimal(0)
    if day_start_equity > 0 and portfolio.equity < day_start_equity:
        daily_loss_pct = (
            (day_start_equity - portfolio.equity) / day_start_equity * Decimal(100)
        )
    limits = asdict(risk_engine.limits)
    return {
        "kill_switch": risk_engine.kill_switch,
        "kill_switch_reason": risk_engine.kill_switch_reason,
        "drawdown_pct": str(portfolio.drawdown_pct),
        "daily_loss_pct": str(daily_loss_pct),
        "day_start_equity": str(day_start_equity),
        "limits": {
            key: value if isinstance(value, bool) else str(value)
            for key, value in limits.items()
        },
        "approved_allocations": len(step.allocation.approved),
        "evaluated_allocations": len(step.allocation.allocations),
        "reserved_gross_notional": str(step.allocation.reserved_gross_notional),
        "authority": "INDEPENDENT_RISK_ENGINE",
        "live_money_enabled": False,
    }
