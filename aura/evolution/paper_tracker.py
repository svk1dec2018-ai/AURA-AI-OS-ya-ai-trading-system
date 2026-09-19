from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Literal

from aura.evolution.core import PerformanceSlice, StrategyGenome
from aura.persistence.wal import JsonlWriteAheadLog, WalEvent
from aura.research.paper_evidence import PaperTradeOutcome, summarize_paper_trades

_TRACKER_SCHEMA_VERSION = 1
_HEADER_EVENT = "paper_tracker_initialized"
_TRADE_EVENT = "paper_trade_recorded"
_INCIDENT_EVENT = "paper_incident_recorded"
IncidentKind = Literal["reconciliation", "operational"]


class PaperGenomePerformanceTracker:
    """Point-in-time paper outcome store keyed by immutable genome hash.

    Only measured closed paper trades enter the evolution paper gate. A strategy
    cannot manufacture a passing paper score from its historical backtest result.
    """

    def __init__(
        self,
        *,
        starting_equity: Decimal,
        journal_path: Path | None = None,
    ) -> None:
        if starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        self.starting_equity = starting_equity
        self.journal_path = journal_path
        self._trades: dict[str, list[PaperTradeOutcome]] = defaultdict(list)
        self._trade_by_key: dict[tuple[str, str], PaperTradeOutcome] = {}
        self._reconciliation_incidents: dict[str, int] = defaultdict(int)
        self._operational_incidents: dict[str, int] = defaultdict(int)
        self._incident_event_ids: set[str] = set()
        self.recovered_events = 0
        self._wal = JsonlWriteAheadLog(journal_path) if journal_path is not None else None
        if self._wal is not None:
            self._initialize_or_replay()

    def record_trade(self, genome: StrategyGenome, trade: PaperTradeOutcome) -> bool:
        genome_hash = genome.content_hash
        key = (genome_hash, trade.trade_id)
        existing = self._trade_by_key.get(key)
        if existing is not None:
            if existing != trade:
                raise ValueError(
                    f"paper trade_id collision for genome {genome.genome_id}: {trade.trade_id}"
                )
            return False
        event_id = _trade_event_id(genome_hash, trade.trade_id)
        if self._wal is not None:
            event = self._wal.append(
                event_type=_TRADE_EVENT,
                payload={
                    "tracker_schema_version": _TRACKER_SCHEMA_VERSION,
                    "genome_hash": genome_hash,
                    "genome_id": genome.genome_id,
                    "trade": trade.model_dump(mode="json"),
                },
                correlation_id=genome.genome_id,
                event_id=event_id,
            )
            self._apply_trade_event(event)
        else:
            self._add_trade(genome_hash, trade)
        return True

    def record_reconciliation_incident(
        self,
        genome: StrategyGenome,
        *,
        incident_id: str,
    ) -> bool:
        return self._record_incident(genome, "reconciliation", incident_id)

    def record_operational_incident(
        self,
        genome: StrategyGenome,
        *,
        incident_id: str,
    ) -> bool:
        return self._record_incident(genome, "operational", incident_id)

    def trade_count(self, genome: StrategyGenome) -> int:
        return len(self._trades[genome.content_hash])

    def reconciliation_incidents_for(self, genome: StrategyGenome) -> int:
        return self._reconciliation_incidents[genome.content_hash]

    def operational_incidents_for(self, genome: StrategyGenome) -> int:
        return self._operational_incidents[genome.content_hash]

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

    def _record_incident(
        self,
        genome: StrategyGenome,
        kind: IncidentKind,
        incident_id: str,
    ) -> bool:
        normalized_id = incident_id.strip()
        if not normalized_id:
            raise ValueError("paper incident_id is required")
        genome_hash = genome.content_hash
        event_id = _incident_event_id(kind, genome_hash, normalized_id)
        if event_id in self._incident_event_ids:
            return False
        if self._wal is not None:
            event = self._wal.append(
                event_type=_INCIDENT_EVENT,
                payload={
                    "tracker_schema_version": _TRACKER_SCHEMA_VERSION,
                    "genome_hash": genome_hash,
                    "genome_id": genome.genome_id,
                    "incident_kind": kind,
                    "incident_id": normalized_id,
                },
                correlation_id=genome.genome_id,
                event_id=event_id,
            )
            self._apply_incident_event(event)
        else:
            self._add_incident(event_id, genome_hash, kind)
        return True

    def _initialize_or_replay(self) -> None:
        assert self._wal is not None
        events = self._wal.read_all()
        if not events:
            self._wal.append(
                event_type=_HEADER_EVENT,
                payload={
                    "tracker_schema_version": _TRACKER_SCHEMA_VERSION,
                    "starting_equity": str(self.starting_equity),
                },
                correlation_id="paper-performance-tracker",
                event_id=_header_event_id(self.starting_equity),
            )
            return

        header = events[0]
        self._validate_schema(header)
        if header.event_type != _HEADER_EVENT:
            raise RuntimeError("paper evidence journal is missing its initialization header")
        try:
            journal_equity = Decimal(str(header.payload["starting_equity"]))
        except Exception as exc:
            raise RuntimeError("paper evidence journal has invalid starting equity") from exc
        if journal_equity != self.starting_equity:
            raise RuntimeError("paper evidence starting_equity changed for an existing journal")

        for event in events[1:]:
            self._validate_schema(event)
            if event.event_type == _TRADE_EVENT:
                self._apply_trade_event(event)
            elif event.event_type == _INCIDENT_EVENT:
                self._apply_incident_event(event)
            else:
                raise RuntimeError(
                    f"unknown paper evidence journal event: {event.event_type}"
                )
            self.recovered_events += 1

    def _apply_trade_event(self, event: WalEvent) -> None:
        try:
            genome_hash = str(event.payload["genome_hash"])
            genome_id = str(event.payload["genome_id"])
            trade = PaperTradeOutcome.model_validate(event.payload["trade"])
        except Exception as exc:
            raise RuntimeError(f"invalid paper trade journal event: {event.event_id}") from exc
        _validate_genome_identity(event, genome_hash, genome_id)
        expected_id = _trade_event_id(genome_hash, trade.trade_id)
        if event.event_id != expected_id:
            raise RuntimeError(f"paper trade event_id mismatch: {event.event_id}")
        key = (genome_hash, trade.trade_id)
        existing = self._trade_by_key.get(key)
        if existing is not None:
            if existing != trade:
                raise RuntimeError(f"paper trade collision in journal: {event.event_id}")
            raise RuntimeError(f"duplicate paper trade journal event: {event.event_id}")
        self._add_trade(genome_hash, trade)

    def _apply_incident_event(self, event: WalEvent) -> None:
        try:
            genome_hash = str(event.payload["genome_hash"])
            genome_id = str(event.payload["genome_id"])
            kind = str(event.payload["incident_kind"])
            incident_id = str(event.payload["incident_id"])
        except Exception as exc:
            raise RuntimeError(f"invalid paper incident journal event: {event.event_id}") from exc
        _validate_genome_identity(event, genome_hash, genome_id)
        if kind not in {"reconciliation", "operational"} or not incident_id.strip():
            raise RuntimeError(f"invalid paper incident journal event: {event.event_id}")
        expected_id = _incident_event_id(kind, genome_hash, incident_id)
        if event.event_id != expected_id:
            raise RuntimeError(f"paper incident event_id mismatch: {event.event_id}")
        if event.event_id in self._incident_event_ids:
            raise RuntimeError(f"duplicate paper incident journal event: {event.event_id}")
        self._add_incident(event.event_id, genome_hash, kind)

    @staticmethod
    def _validate_schema(event: WalEvent) -> None:
        if event.payload.get("tracker_schema_version") != _TRACKER_SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported paper evidence schema in event {event.event_id}"
            )

    def _add_trade(self, genome_hash: str, trade: PaperTradeOutcome) -> None:
        self._trades[genome_hash].append(trade)
        self._trade_by_key[(genome_hash, trade.trade_id)] = trade

    def _add_incident(
        self,
        event_id: str,
        genome_hash: str,
        kind: str,
    ) -> None:
        self._incident_event_ids.add(event_id)
        if kind == "reconciliation":
            self._reconciliation_incidents[genome_hash] += 1
        else:
            self._operational_incidents[genome_hash] += 1


def _header_event_id(starting_equity: Decimal) -> str:
    return f"paper-tracker:initialized:{starting_equity}"


def _trade_event_id(genome_hash: str, trade_id: str) -> str:
    return f"paper-trade:{genome_hash}:{trade_id}"


def _incident_event_id(kind: str, genome_hash: str, incident_id: str) -> str:
    return f"paper-incident:{kind}:{genome_hash}:{incident_id}"


def _validate_genome_identity(
    event: WalEvent,
    genome_hash: str,
    genome_id: str,
) -> None:
    is_hex_hash = len(genome_hash) == 64 and all(
        character in "0123456789abcdef" for character in genome_hash
    )
    if (
        not is_hex_hash
        or not genome_id.endswith(f":{genome_hash[:16]}")
        or event.correlation_id != genome_id
    ):
        raise RuntimeError(f"invalid paper genome identity in event {event.event_id}")
