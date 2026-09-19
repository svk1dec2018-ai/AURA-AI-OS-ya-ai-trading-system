from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from aura.execution.demo_guard import DemoExecutionGuard
from aura.execution.mt5_protected_demo import (
    ProtectedMT5DemoBroker,
    ProtectedMT5DemoConfig,
)
from aura.persistence.atomic import atomic_write_json
from aura.persistence.recovery import recover_financial_state
from aura.runtime.mt5_learning_daemon import (
    MT5SelfEvolvingPaperDaemon,
    build_mt5_self_evolving_paper_daemon,
)
from aura.runtime.mt5_paper_daemon import MT5AllMarketPaperConfig, MT5AllMarketPaperDaemon


class MT5AutonomousDemoBase(MT5AllMarketPaperDaemon):
    """Broker-DEMO base with explicit live-money and fund-movement locks."""

    def _write_status(self, step) -> None:
        super()._write_status(step)
        payload = json.loads(self.status_path.read_text(encoding="utf-8"))
        payload.update(
            {
                "mode": "MT5_BROKER_DEMO_SELF_EVOLVING_AUTONOMOUS",
                "broker_order_submission_enabled": True,
                "broker_environment": "DEMO_ONLY",
                "native_sl_tp_required": True,
                "aura_magic_isolation": True,
                "pyramiding_enabled": False,
                "strategy_research_enabled": True,
                "paper_champion_promotion_enabled": True,
                "real_money_enabled": False,
                "withdrawals_enabled": False,
                "fund_transfers_enabled": False,
            }
        )
        atomic_write_json(self.status_path, payload)


async def build_mt5_autonomous_demo_daemon(
    config: MT5AllMarketPaperConfig | None = None,
    *,
    protection: ProtectedMT5DemoConfig | None = None,
    research_every_new_samples: int = 100,
) -> MT5SelfEvolvingPaperDaemon:
    """Build AURA's all-market, self-evolving, actual MT5 DEMO runtime.

    It reuses the existing live MT5 data plane, multi-agent desk, deterministic
    CEO, independent RiskEngine, forward-only learning, opportunity audit and
    champion/challenger research. Only approved orders are routed to a verified
    DEMO account through ProtectedMT5DemoBroker. Financial WAL state is restored
    before new decisions and live-money/fund-transfer capability is absent.
    """

    effective = config or MT5AllMarketPaperConfig(
        state_dir=Path("runtime/mt5_autonomous_demo")
    )
    if effective.state_dir == Path("runtime/mt5_all_market_paper"):
        effective = replace(effective, state_dir=Path("runtime/mt5_autonomous_demo"))

    daemon = await build_mt5_self_evolving_paper_daemon(
        effective,
        research_every_new_samples=research_every_new_samples,
    )
    original = daemon.base
    account = original.gateway.account_info()
    if account is None:
        original.gateway.shutdown()
        raise RuntimeError(f"MT5 account_info failed: {original.gateway.last_error()}")
    DemoExecutionGuard.assert_mt5_demo_account(account)
    account_data = _asdict(account)
    starting_cash = _load_or_create_account_baseline(
        original.config.state_dir,
        account_data,
    )

    coordinator = original.coordinator
    recovered = recover_financial_state(
        coordinator.financial_journal.wal,
        starting_cash=starting_cash,
        instrument_specs=coordinator.ledger.instrument_specs,
    )
    coordinator.ledger = recovered.ledger
    coordinator.starting_cash = starting_cash
    coordinator.day_start_equity = starting_cash
    if recovered.kill_switch:
        coordinator.risk_engine.engage_kill_switch(
            recovered.kill_switch_reason or "restored financial kill switch"
        )

    broker = ProtectedMT5DemoBroker(original.gateway, config=protection)
    broker.restore_orders(state.request for state in recovered.orders.values())
    coordinator.broker = broker

    effective_config = replace(original.config, starting_cash=starting_cash)
    autonomous_base = MT5AutonomousDemoBase(
        config=effective_config,
        gateway=original.gateway,
        source=original.source,
        coordinator=coordinator,
        bootstrap=original.bootstrap,
    )
    daemon.base = autonomous_base
    daemon.brain_state_dir = autonomous_base.config.state_dir / "brain"
    daemon.brain_state_dir.mkdir(parents=True, exist_ok=True)
    return daemon


def _load_or_create_account_baseline(state_dir: Path, account: dict[str, Any]) -> Decimal:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "account_baseline.json"
    login = int(account.get("login", 0))
    server = str(account.get("server", ""))
    balance = Decimal(str(account.get("balance", 0)))
    if login <= 0 or not server or balance <= 0:
        raise RuntimeError("MT5 DEMO account returned invalid baseline identity/balance")

    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("login", 0)) != login or str(payload.get("server", "")) != server:
            raise RuntimeError(
                "AURA DEMO state belongs to a different MT5 account; use a fresh state directory"
            )
        baseline = Decimal(str(payload.get("starting_balance", 0)))
        if baseline <= 0:
            raise RuntimeError("stored MT5 account baseline is invalid")
        return baseline

    financial_path = state_dir / "financial.jsonl"
    if financial_path.exists() and financial_path.stat().st_size > 0:
        raise RuntimeError(
            "financial WAL exists without account baseline; refusing ambiguous DEMO recovery"
        )
    payload = {
        "login": login,
        "server": server,
        "currency": str(account.get("currency", "")),
        "starting_balance": str(balance),
        "environment": "DEMO_ONLY",
        "real_money_enabled": False,
    }
    atomic_write_json(path, payload)
    return balance


def _asdict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    return dict(vars(value))
