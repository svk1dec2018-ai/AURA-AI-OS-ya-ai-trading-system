from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from aura.evolution.core import PerformanceSlice, StrategyGenome
from aura.research.paper_evidence import PaperTradeOutcome, summarize_paper_trades


class PaperGenomePerformanceTracker:
    """Point-in-time paper outcome store keyed by immutable genome hash.

    Only measured closed paper trades enter the evolution paper gate. A strategy
    cannot manufacture a passing paper score from its historical backtest result.
    """

    def __init__(self, *, starting_equity: Decimal) -> None:
        if starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        self.starting_equity = starting_equity
        self._trades: dict[str, list[PaperTradeOutcome]] = defaultdict(list)
        self._reconciliation_incidents: dict[str, int] = defaultdict(int)
        self._operational_incidents: dict[str, int] = defaultdict(int)

    def record_trade(self, genome: StrategyGenome, trade: PaperTradeOutcome) -> None:
        self._trades[genome.content_hash].append(trade)

    def record_reconciliation_incident(self, genome: StrategyGenome) -> None:
        self._reconciliation_incidents[genome.content_hash] += 1

    def record_operational_incident(self, genome: StrategyGenome) -> None:
        self._operational_incidents[genome.content_hash] += 1

    def trade_count(self, genome: StrategyGenome) -> int:
        return len(self._trades[genome.content_hash])

    def performance_for(self, genome: StrategyGenome) -> PerformanceSlice | None:
        trades = self._trades.get(genome.content_hash, [])
        if not trades:
            return None
        summary = summarize_paper_trades(
            trades,
            starting_equity=self.starting_equity,
            reconciliation_incidents=self._reconciliation_incidents[genome.content_hash],
            operational_incidents=self._operational_incidents[genome.content_hash],
        )
        net_return_pct = float(summary.net_pnl / self.starting_equity * Decimal(100))
        expectancy_pct = float(
            summary.expectancy_per_trade / self.starting_equity * Decimal(100)
        )
        return PerformanceSlice(
            label="live_paper",
            trades=summary.trades,
            net_return_pct=net_return_pct,
            expectancy_pct=expectancy_pct,
            profit_factor=summary.profit_factor,
            max_drawdown_pct=summary.max_drawdown_pct,
            sharpe=0.0,
            win_rate=summary.win_rate,
            avg_slippage_bps=0.0,
        )
