from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from aura.backtest.engine import BacktestEngine
from aura.core.pipeline import DecisionPipeline
from aura.data.mt5_demo import MT5DemoClosedCandleSource, OfficialMT5Gateway
from aura.portfolio.instruments import AccountingMode, InstrumentLedgerSpec
from aura.research.blueprint_compiler import compile_blueprint
from aura.research.strategy_factory import StrategyBlueprint
from aura.risk.engine import RiskEngine, RiskLimits
from aura.risk.quantity import QuantityRule

BACKTEST_SCHEMA_VERSION = 1


def run_candidate_backtest(
    candidate: dict[str, Any],
    *,
    symbol: str,
    timeframe: str,
    bars: int = 1000,
    starting_cash: Decimal = Decimal(100000),
    requested_quantity: Decimal | None = None,
    fee_bps: Decimal = Decimal(0),
    slippage_bps: Decimal = Decimal(1),
    gateway: OfficialMT5Gateway | None = None,
) -> dict[str, Any]:
    """Backtest one immutable Algo Studio candidate on closed MT5 DEMO candles.

    The runner is research-only. It performs no broker order submission, does not
    promote the candidate and does not set any live approval flag. Strategy
    signals still pass through AURA's shared ``DecisionPipeline`` and independent
    ``RiskEngine`` before the causal backtester fills them on a later candle.
    """

    if not candidate.get("research_only", True):
        raise ValueError("only research candidates may be run from Algo Studio")
    if not 100 <= bars <= 20_000:
        raise ValueError("bars must be between 100 and 20000")
    if starting_cash <= 0:
        raise ValueError("starting_cash must be positive")
    if fee_bps < 0 or slippage_bps < 0:
        raise ValueError("fee/slippage bps cannot be negative")

    blueprint_payload = candidate.get("blueprint")
    if not isinstance(blueprint_payload, dict):
        raise TypeError("candidate does not contain a valid strategy blueprint")
    blueprint = StrategyBlueprint.model_validate(blueprint_payload)
    compiled = compile_blueprint(blueprint)
    if bars <= compiled.warmup_bars + 5:
        raise ValueError(
            f"bars must exceed strategy warmup ({compiled.warmup_bars}) by at least 6"
        )

    normalized_symbol = symbol.strip()
    if not normalized_symbol:
        raise ValueError("symbol is required")
    if blueprint.market_scope and not _scope_matches(normalized_symbol, blueprint.market_scope):
        raise ValueError(
            f"symbol {normalized_symbol} is outside candidate market scope: "
            f"{', '.join(blueprint.market_scope)}"
        )
    if blueprint.timeframe_scope and timeframe not in blueprint.timeframe_scope:
        raise ValueError(
            f"timeframe {timeframe} is outside candidate timeframe scope: "
            f"{', '.join(blueprint.timeframe_scope)}"
        )

    owned_gateway = gateway is None
    effective_gateway = gateway or OfficialMT5Gateway()
    try:
        account = effective_gateway.connect_current_demo_session()
        symbol_info = effective_gateway.symbol_info(normalized_symbol)
        if symbol_info is None:
            raise ValueError(f"symbol is not exposed by MT5: {normalized_symbol}")
        effective_gateway.symbol_select(normalized_symbol, True)
        candles = list(
            MT5DemoClosedCandleSource(effective_gateway).fetch(
                normalized_symbol,
                timeframe,
                count=bars,
            )
        )
        if len(candles) <= compiled.warmup_bars + 5:
            raise RuntimeError(
                f"MT5 returned {len(candles)} closed candles; strategy needs more history"
            )

        contract_size = _positive_decimal(_field(symbol_info, "trade_contract_size"), Decimal(1))
        volume_min = _positive_decimal(_field(symbol_info, "volume_min"), Decimal("0.01"))
        volume_step = _positive_decimal(_field(symbol_info, "volume_step"), volume_min)
        volume_max_raw = _field(symbol_info, "volume_max")
        volume_max = _positive_decimal(volume_max_raw, Decimal(0)) if volume_max_raw else None
        if volume_max is not None and volume_max <= 0:
            volume_max = None
        quantity = requested_quantity or volume_min
        if quantity <= 0:
            raise ValueError("requested_quantity must be positive")

        quantity_rule = QuantityRule(
            minimum=volume_min,
            step=volume_step,
            maximum=volume_max,
        )
        risk = RiskEngine(
            RiskLimits(
                max_order_notional_pct=Decimal(2),
                max_gross_exposure_pct=Decimal(100),
                max_symbol_exposure_pct=Decimal(25),
                max_drawdown_pct=Decimal(10),
                max_daily_loss_pct=Decimal(4),
                allow_short=True,
            ),
            notional_multipliers={normalized_symbol: contract_size},
            quantity_rules={normalized_symbol: quantity_rule},
        )
        engine = BacktestEngine(
            DecisionPipeline(compiled.strategy, risk),
            starting_cash=starting_cash,
            requested_quantity=quantity,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            instrument_specs={
                normalized_symbol: InstrumentLedgerSpec(
                    accounting=AccountingMode.DERIVATIVE,
                    contract_multiplier=contract_size,
                )
            },
        )
        result = engine.run(candles, signal_start_index=compiled.warmup_bars)
        total_return_pct = (
            (result.ending_equity / result.starting_equity - Decimal(1)) * Decimal(100)
            if result.starting_equity > 0
            else Decimal(0)
        )
        payload = {
            "schema_version": BACKTEST_SCHEMA_VERSION,
            "ok": True,
            "research_only": True,
            "live_approved": False,
            "candidate_id": candidate.get("candidate_id"),
            "candidate_content_hash": candidate.get("strategy_version", {}).get("content_hash"),
            "compiled_strategy_id": compiled.strategy_id,
            "created_at": datetime.now(UTC).isoformat(),
            "data": {
                "source": "MT5_DEMO_CLOSED_CANDLES",
                "symbol": normalized_symbol,
                "timeframe": timeframe,
                "bars_requested": bars,
                "bars_used": len(candles),
                "first_open_time": candles[0].open_time.isoformat(),
                "last_close_time": candles[-1].close_time.isoformat(),
                "account_server": account.server,
                "account_login_last4": str(account.login)[-4:],
            },
            "assumptions": {
                "starting_cash": str(starting_cash),
                "requested_quantity": str(quantity),
                "fee_bps": str(fee_bps),
                "slippage_bps": str(slippage_bps),
                "contract_multiplier": str(contract_size),
                "volume_min": str(volume_min),
                "volume_step": str(volume_step),
                "signal_warmup_bars": compiled.warmup_bars,
                "execution_semantics": "signal_after_close_fill_on_later_eligible_candle",
            },
            "metrics": {
                "starting_equity": str(result.starting_equity),
                "ending_equity": str(result.ending_equity),
                "total_return_pct": str(total_return_pct),
                "realized_pnl": str(result.realized_pnl),
                "unrealized_pnl": str(result.unrealized_pnl),
                "max_drawdown_pct": str(result.max_drawdown_pct),
                "orders": result.orders,
                "fills": result.fills,
                "rejected_signals": result.rejected_signals,
            },
            "equity_curve": [str(value) for value in result.equity_curve],
            "fills": [fill.model_dump(mode="json") for fill in result.fill_records],
            "validation": {
                "completed": ["compile", "causal_backtest"],
                "next_required": "purged_walk_forward",
                "auto_promoted": False,
                "human_approval_required_for_live": True,
            },
        }
        payload["artifact_hash"] = _content_hash(payload)
        return payload
    finally:
        if owned_gateway:
            effective_gateway.shutdown()


def persist_backtest(result: dict[str, Any], directory: Path) -> Path:
    if not result.get("research_only") or result.get("live_approved"):
        raise ValueError("only non-live research backtests may be persisted here")
    artifact_hash = str(result.get("artifact_hash") or "").strip()
    if not artifact_hash:
        raise ValueError("backtest artifact_hash is required")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{artifact_hash}.json"
    temp = destination.with_suffix(".tmp")
    temp.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    temp.replace(destination)
    return destination


def _scope_matches(symbol: str, scope: tuple[str, ...]) -> bool:
    upper = symbol.upper()
    return any(
        upper == item.upper()
        or upper.startswith(item.upper())
        or item.upper().startswith(upper)
        for item in scope
    )


def _field(source: Any, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _positive_decimal(value: Any, fallback: Decimal) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return fallback
    return parsed if parsed > 0 else fallback


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
