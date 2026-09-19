from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from aura.research.lifecycle import EvidenceKind, ValidationEvidence


class PaperTradeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    gross_pnl: Decimal
    fees: Decimal = Field(default=Decimal(0), ge=0)
    slippage_cost: Decimal = Field(default=Decimal(0), ge=0)

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees - self.slippage_cost


class PaperPerformanceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    trades: int = Field(ge=0)
    winning_trades: int = Field(ge=0)
    losing_trades: int = Field(ge=0)
    net_pnl: Decimal
    expectancy_per_trade: Decimal
    profit_factor: float = Field(ge=0.0)
    win_rate: float = Field(ge=0.0, le=1.0)
    max_drawdown_pct: float = Field(ge=0.0)
    reconciliation_incidents: int = Field(ge=0)
    operational_incidents: int = Field(ge=0)


@dataclass(slots=True, frozen=True)
class PaperValidationThresholds:
    min_trades: int = 100
    min_expectancy_per_trade: Decimal = Decimal(0)
    min_profit_factor: float = 1.10
    max_drawdown_pct: float = 15.0
    max_reconciliation_incidents: int = 0
    max_operational_incidents: int = 0

    def __post_init__(self) -> None:
        if self.min_trades <= 0:
            raise ValueError("paper min_trades must be positive")
        if self.min_profit_factor < 0 or self.max_drawdown_pct < 0:
            raise ValueError("paper performance thresholds cannot be negative")
        if self.max_reconciliation_incidents < 0 or self.max_operational_incidents < 0:
            raise ValueError("paper incident thresholds cannot be negative")


class PaperValidationDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    reasons: tuple[str, ...]


def summarize_paper_trades(
    trades: list[PaperTradeOutcome] | tuple[PaperTradeOutcome, ...],
    *,
    starting_equity: Decimal,
    reconciliation_incidents: int = 0,
    operational_incidents: int = 0,
) -> PaperPerformanceSummary:
    if starting_equity <= 0:
        raise ValueError("starting_equity must be positive")
    if reconciliation_incidents < 0 or operational_incidents < 0:
        raise ValueError("incident counts cannot be negative")

    net_values = [trade.net_pnl for trade in trades]
    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value < 0]
    net_pnl = sum(net_values, Decimal(0))
    expectancy = net_pnl / Decimal(len(trades)) if trades else Decimal(0)
    gross_profit = sum(wins, Decimal(0))
    gross_loss = abs(sum(losses, Decimal(0)))
    if gross_loss > 0:
        profit_factor = float(gross_profit / gross_loss)
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    equity = starting_equity
    peak = starting_equity
    max_drawdown = Decimal(0)
    for value in net_values:
        equity += value
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * Decimal(100))

    return PaperPerformanceSummary(
        trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        net_pnl=net_pnl,
        expectancy_per_trade=expectancy,
        profit_factor=profit_factor,
        win_rate=len(wins) / len(trades) if trades else 0.0,
        max_drawdown_pct=float(max_drawdown),
        reconciliation_incidents=reconciliation_incidents,
        operational_incidents=operational_incidents,
    )


def evaluate_paper_performance(
    summary: PaperPerformanceSummary,
    *,
    thresholds: PaperValidationThresholds | None = None,
) -> PaperValidationDecision:
    limits = thresholds or PaperValidationThresholds()
    reasons: list[str] = []
    if summary.trades < limits.min_trades:
        reasons.append(f"paper trades {summary.trades} < required {limits.min_trades}")
    if summary.expectancy_per_trade <= limits.min_expectancy_per_trade:
        reasons.append(
            "paper expectancy did not clear threshold: "
            f"{summary.expectancy_per_trade} <= {limits.min_expectancy_per_trade}"
        )
    if summary.profit_factor < limits.min_profit_factor:
        reasons.append(
            f"paper profit factor {summary.profit_factor:.4f} < {limits.min_profit_factor:.4f}"
        )
    if summary.max_drawdown_pct > limits.max_drawdown_pct:
        reasons.append(
            f"paper drawdown {summary.max_drawdown_pct:.4f}% > {limits.max_drawdown_pct:.4f}%"
        )
    if summary.reconciliation_incidents > limits.max_reconciliation_incidents:
        reasons.append(
            "paper reconciliation incidents "
            f"{summary.reconciliation_incidents} > {limits.max_reconciliation_incidents}"
        )
    if summary.operational_incidents > limits.max_operational_incidents:
        reasons.append(
            f"paper operational incidents {summary.operational_incidents} > "
            f"{limits.max_operational_incidents}"
        )
    return PaperValidationDecision(passed=not reasons, reasons=tuple(reasons))


def build_paper_validation_evidence(
    summary: PaperPerformanceSummary,
    *,
    thresholds: PaperValidationThresholds | None = None,
    created_at: datetime | None = None,
) -> ValidationEvidence:
    limits = thresholds or PaperValidationThresholds()
    decision = evaluate_paper_performance(summary, thresholds=limits)
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    payload = {
        "summary": summary.model_dump(mode="json"),
        "thresholds": {
            "min_trades": limits.min_trades,
            "min_expectancy_per_trade": str(limits.min_expectancy_per_trade),
            "min_profit_factor": limits.min_profit_factor,
            "max_drawdown_pct": limits.max_drawdown_pct,
            "max_reconciliation_incidents": limits.max_reconciliation_incidents,
            "max_operational_incidents": limits.max_operational_incidents,
        },
        "decision": decision.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ValidationEvidence(
        kind=EvidenceKind.PAPER_TRADING,
        passed=decision.passed,
        artifact_hash=digest,
        created_at=timestamp,
        notes="; ".join(decision.reasons) if decision.reasons else "paper thresholds passed",
    )
