from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from aura.data.mt5_demo import OfficialMT5Gateway
from aura.execution.mt5_demo_broker import MT5DemoBroker, MT5DemoBrokerConfig
from aura.persistence.recovery import FinancialEventJournal
from aura.persistence.wal import JsonlWriteAheadLog
from aura.runtime.mt5_paper_daemon import (
    MT5AllMarketPaperConfig,
    MT5AllMarketPaperDaemon,
    build_mt5_all_market_paper_daemon,
)


@dataclass(slots=True, frozen=True)
class MT5AutonomousDemoConfig:
    state_dir: Path = Path("runtime/mt5_autonomous_demo")
    max_demo_orders: int = 5
    reconcile_every_batches: int = 5
    fill_settle_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.max_demo_orders <= 0:
            raise ValueError("max_demo_orders must be positive")
        if self.reconcile_every_batches <= 0:
            raise ValueError("reconcile_every_batches must be positive")
        if self.fill_settle_seconds < 0:
            raise ValueError("fill_settle_seconds cannot be negative")


@dataclass(slots=True)
class MT5AutonomousDemoCounters:
    batches: int = 0
    opportunities: int = 0
    risk_approved_intents: int = 0
    broker_submissions: int = 0
    broker_fills: int = 0
    broker_safety_blocks: int = 0
    broker_state_checks: int = 0


class MT5AutonomousDemoDaemon:
    """Mirror only AURA RiskEngine-approved intents into a verified MT5 DEMO account.

    The existing all-market paper coordinator remains the decision authority. This
    bridge consumes only its submitted orders, which are downstream of the scanner,
    agent/CEO policy and RiskEngine. It can never connect through a live-account
    path because the shared OfficialMT5Gateway has already passed connect_demo().
    """

    def __init__(
        self,
        *,
        decision_daemon: MT5AllMarketPaperDaemon,
        broker: MT5DemoBroker,
        config: MT5AutonomousDemoConfig,
    ) -> None:
        self.decision_daemon = decision_daemon
        self.broker = broker
        self.config = config
        self.counters = MT5AutonomousDemoCounters()
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.status_path = self.config.state_dir / "status.json"
        self.journal = FinancialEventJournal(
            JsonlWriteAheadLog(self.config.state_dir / "broker_financial.jsonl")
        )
        self._running = False

    async def run(self, *, max_batches: int | None = None) -> MT5AutonomousDemoCounters:
        if max_batches is not None and max_batches <= 0:
            raise ValueError("max_batches must be positive")
        if self._running:
            raise RuntimeError("MT5 autonomous DEMO daemon is already running")
        self._require_flat_broker_start()
        self._running = True
        await self.decision_daemon.coordinator.start()
        await self.broker.connect()
        self._write_status(None, None)
        try:
            async for batch in self.decision_daemon.source.batches():
                step = await self.decision_daemon.coordinator.on_batch(batch)
                self.counters.batches += 1
                self.counters.opportunities += len(step.scan.opportunities)
                self.counters.risk_approved_intents += len(step.submitted_orders)

                latest_error: str | None = None
                for submitted in step.submitted_orders:
                    if self.counters.broker_submissions >= self.config.max_demo_orders:
                        break
                    correlation_id = f"mt5-demo:{submitted.order.order_id}"
                    try:
                        self.journal.record_order_created(
                            submitted.order,
                            correlation_id=correlation_id,
                        )
                        await self.broker.submit_order(submitted.order)
                        self.journal.record_order_submitted(
                            submitted.order.order_id,
                            correlation_id=correlation_id,
                        )
                        self.journal.record_order_acknowledged(
                            submitted.order.order_id,
                            correlation_id=correlation_id,
                        )
                        self.counters.broker_submissions += 1
                    except RuntimeError as exc:
                        latest_error = str(exc)
                        if "safety block" in latest_error.lower():
                            self.counters.broker_safety_blocks += 1
                            continue
                        self.decision_daemon.coordinator.risk_engine.engage_kill_switch(
                            f"MT5 DEMO broker submission failure: {latest_error}"
                        )
                        self.journal.record_kill_switch_engaged(
                            self.decision_daemon.coordinator.risk_engine.kill_switch_reason,
                            correlation_id="mt5-demo:broker-failure",
                        )
                        raise

                if self.config.fill_settle_seconds:
                    await asyncio.sleep(self.config.fill_settle_seconds)
                for fill in await self.broker.poll_fills_once():
                    self.journal.record_fill(
                        fill,
                        correlation_id=f"mt5-demo-fill:{fill.order_id}",
                    )
                    self.counters.broker_fills += 1

                if self.counters.batches % self.config.reconcile_every_batches == 0:
                    self._broker_state_check()
                self._write_status(step, latest_error)

                if (
                    self.counters.broker_submissions >= self.config.max_demo_orders
                    or (max_batches is not None and self.counters.batches >= max_batches)
                ):
                    self.decision_daemon.source.stop()
                    break
        finally:
            try:
                if self._running:
                    try:
                        for fill in await self.broker.poll_fills_once():
                            self.journal.record_fill(
                                fill,
                                correlation_id=f"mt5-demo-fill:{fill.order_id}",
                            )
                            self.counters.broker_fills += 1
                    finally:
                        self._broker_state_check()
            finally:
                await self.broker.disconnect()
                await self.decision_daemon.coordinator.stop()
                self.decision_daemon.gateway.shutdown()
                self._running = False
                self._write_status(None, None)
        return self.counters

    def _require_flat_broker_start(self) -> None:
        rows = self.decision_daemon.gateway.positions_get()
        if rows is None:
            raise RuntimeError(
                f"MT5 positions_get failed before startup: {self.decision_daemon.gateway.last_error()}"
            )
        if rows:
            raise RuntimeError(
                "MT5 autonomous DEMO startup blocked: close all existing MT5 positions first"
            )

    def _broker_state_check(self) -> None:
        self.broker.open_order_snapshots()
        self.broker.position_snapshots()
        self.counters.broker_state_checks += 1

    def _write_status(self, step, latest_error: str | None) -> None:
        positions = []
        orders = []
        if self._running:
            try:
                positions = [
                    {"symbol": item.symbol, "quantity": str(item.quantity)}
                    for item in self.broker.position_snapshots()
                ]
                orders = [
                    {
                        "broker_order_id": item.broker_order_id,
                        "client_order_id": item.client_order_id,
                        "symbol": item.symbol,
                        "side": item.side.value,
                        "quantity": str(item.quantity),
                        "filled_quantity": str(item.filled_quantity),
                        "status": item.status.value,
                    }
                    for item in self.broker.open_order_snapshots()
                ]
            except RuntimeError as exc:
                latest_error = latest_error or str(exc)
        payload: dict[str, object] = {
            "mode": "MT5_AUTONOMOUS_DEMO",
            "demo_only": True,
            "real_money_enabled": False,
            "updated_at": datetime.now(UTC).isoformat(),
            "counters": {
                "batches": self.counters.batches,
                "opportunities": self.counters.opportunities,
                "risk_approved_intents": self.counters.risk_approved_intents,
                "broker_submissions": self.counters.broker_submissions,
                "broker_fills": self.counters.broker_fills,
                "broker_safety_blocks": self.counters.broker_safety_blocks,
                "broker_state_checks": self.counters.broker_state_checks,
            },
            "risk_kill_switch": self.decision_daemon.coordinator.risk_engine.kill_switch,
            "risk_kill_switch_reason": (
                self.decision_daemon.coordinator.risk_engine.kill_switch_reason
            ),
            "broker_positions": positions,
            "broker_open_orders": orders,
            "latest_error": latest_error,
        }
        if step is not None:
            payload["latest_decision"] = {
                "close_time": step.close_time_iso,
                "opportunities": len(step.scan.opportunities),
                "risk_approved_orders": [
                    {
                        "symbol": item.order.symbol,
                        "side": item.order.side.value,
                        "quantity": str(item.order.quantity),
                    }
                    for item in step.submitted_orders
                ],
            }
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.status_path)


async def build_mt5_autonomous_demo_daemon(
    *,
    paper_config: MT5AllMarketPaperConfig | None = None,
    demo_config: MT5AutonomousDemoConfig | None = None,
    gateway: OfficialMT5Gateway | None = None,
) -> MT5AutonomousDemoDaemon:
    paper_config = paper_config or MT5AllMarketPaperConfig(
        state_dir=Path("runtime/mt5_autonomous_demo/decision_paper")
    )
    demo_config = demo_config or MT5AutonomousDemoConfig()
    decision_daemon = await build_mt5_all_market_paper_daemon(
        paper_config,
        gateway=gateway,
    )
    broker = MT5DemoBroker(
        decision_daemon.gateway,
        config=MT5DemoBrokerConfig(
            stop_loss_bps=Decimal(50),
            take_profit_bps=Decimal(100),
            block_existing_aura_position=True,
        ),
    )
    return MT5AutonomousDemoDaemon(
        decision_daemon=decision_daemon,
        broker=broker,
        config=demo_config,
    )
