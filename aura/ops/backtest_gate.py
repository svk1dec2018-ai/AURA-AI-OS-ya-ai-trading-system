from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from aura.backtest.engine import BacktestEngine
from aura.core.pipeline import DecisionPipeline
from aura.domain.models import NormalizedCandle, OrderRequest, Side, SignalIntent, StrategySignal
from aura.execution.fill_model import CandleExecutionModel
from aura.execution.paper import PaperBroker, PaperExecutionConfig
from aura.ops.broker_conformance_gate import PHASE_FOUR_EVIDENCE
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.market_data_gate import PHASE_FIVE_EVIDENCE
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.ops.risk_engine_gate import PHASE_THREE_EVIDENCE
from aura.ops.state_engine_gate import PHASE_TWO_EVIDENCE
from aura.risk.engine import RiskEngine, RiskLimits
from aura.strategy.base import Strategy

OUTPUT_DIR = Path("artifacts/governance")
BACKTEST_REPORT = OUTPUT_DIR / "backtest_report.json"
BIAS_REPORT = OUTPUT_DIR / "bias_detection_report.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_SIX_EVIDENCE = {
    "Backtest report": BACKTEST_REPORT.as_posix(),
    "Bias detection report": BIAS_REPORT.as_posix(),
}

_START = datetime(2026, 1, 1, tzinfo=UTC)


class _OneShotStrategy(Strategy):
    strategy_id = "phase6.execution-parity-fixture"
    warmup_bars = 2

    def __init__(self) -> None:
        self.history_lengths: list[int] = []

    def on_closed_candle(self, history):
        self.history_lengths.append(len(history))
        if len(history) != 2:
            return None
        latest = history[-1]
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=latest.symbol,
            intent=SignalIntent.LONG,
            confidence=1.0,
            reference_price=latest.close,
            generated_at=latest.close_time,
            reason="deterministic internal parity fixture",
        )


class _FutureDatedStrategy(Strategy):
    strategy_id = "phase6.future-dated-fixture"

    def on_closed_candle(self, history):
        latest = history[-1]
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=latest.symbol,
            intent=SignalIntent.LONG,
            confidence=1.0,
            reference_price=latest.close,
            generated_at=latest.close_time + timedelta(microseconds=1),
            reason="deliberately invalid future timestamp",
        )


def _candle(index: int, open_price: str, close_price: str) -> NormalizedCandle:
    start = _START + timedelta(minutes=index)
    open_value = Decimal(open_price)
    close_value = Decimal(close_price)
    return NormalizedCandle(
        symbol="AURA-PHASE6-FIXTURE",
        venue="INTERNAL_FIXTURE",
        timeframe="1m",
        open_time=start,
        close_time=start + timedelta(minutes=1),
        open=open_value,
        high=max(open_value, close_value),
        low=min(open_value, close_value),
        close=close_value,
        volume=Decimal(100),
        closed=True,
    )


def _pipeline(strategy: Strategy) -> DecisionPipeline:
    return DecisionPipeline(
        strategy,
        RiskEngine(
            RiskLimits(
                max_order_notional_pct=Decimal(100),
                max_gross_exposure_pct=Decimal(100),
            )
        ),
    )


def build_backtest_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    candles = (
        _candle(0, "100", "101"),
        _candle(1, "101", "102"),
        _candle(2, "110", "111"),
    )
    strategy = _OneShotStrategy()
    engine = BacktestEngine(
        _pipeline(strategy),
        starting_cash=Decimal(10000),
        requested_quantity=Decimal(2),
        fee_bps=Decimal(10),
        slippage_bps=Decimal(10),
    )
    result = engine.run(list(candles))
    if len(result.fill_records) != 1:
        raise RuntimeError("Phase 6 parity fixture did not produce exactly one backtest fill")
    backtest_fill = result.fill_records[0]
    paper_fill, paper_model = asyncio.run(_paper_fill(candles))
    parity = {
        "fill_price_equal": backtest_fill.price == paper_fill.price,
        "fee_equal": backtest_fill.fee == paper_fill.fee,
        "quantity_equal": backtest_fill.quantity == paper_fill.quantity,
        "shared_fill_model_type": (
            isinstance(engine.execution_model, CandleExecutionModel)
            and isinstance(paper_model, CandleExecutionModel)
        ),
    }
    if not all(parity.values()):
        raise RuntimeError("backtest and paper execution semantics diverged")

    future_signal_blocked = _future_signal_is_blocked(candles)
    out_of_order_blocked = _out_of_order_is_blocked(candles)
    if not future_signal_blocked or not out_of_order_blocked:
        raise RuntimeError("look-ahead bias probes did not fail closed")
    bias_report = {
        "schema_version": 1,
        "phase": 6,
        "decision": "PASS",
        "fixture_type": "deterministic_internal_backtest_fixture",
        "probes": {
            "strategy_received_incremental_history_lengths": strategy.history_lengths,
            "future_dated_signal_blocked": future_signal_blocked,
            "out_of_order_series_blocked": out_of_order_blocked,
            "signal_candle_index": 1,
            "fill_candle_index": 2,
            "same_candle_fill_forbidden": True,
            "fill_timestamp_not_before_signal": (
                backtest_fill.timestamp >= candles[1].close_time
            ),
        },
        "external_market_data_claimed": False,
    }
    bias_report["deterministic_fingerprint"] = _sha256(bias_report)

    backtest_report = {
        "schema_version": 1,
        "phase": 6,
        "decision": "PASS",
        "fixture_type": "deterministic_internal_backtest_fixture",
        "shared_components": {
            "decision_pipeline": "aura.core.pipeline.DecisionPipeline",
            "fill_and_cost_model": "aura.execution.fill_model.CandleExecutionModel",
        },
        "execution_assumptions": {
            "fee_bps": "10",
            "slippage_bps": "10",
            "fill_timing": "next eligible candle",
        },
        "backtest": {
            "orders": result.orders,
            "fills": result.fills,
            "fill_price": str(backtest_fill.price),
            "fee": str(backtest_fill.fee),
            "ending_equity": str(result.ending_equity),
        },
        "paper": {
            "fills": 1,
            "fill_price": str(paper_fill.price),
            "fee": str(paper_fill.fee),
        },
        "parity": parity,
        "strategy_performance_claimed": False,
        "external_broker_execution_claimed": False,
        "live_money_enabled": False,
    }
    backtest_report["deterministic_fingerprint"] = _sha256(backtest_report)
    return backtest_report, bias_report


async def _paper_fill(
    candles: tuple[NormalizedCandle, ...],
):
    broker = PaperBroker(
        PaperExecutionConfig(fee_bps=Decimal(10), slippage_bps=Decimal(10))
    )
    await broker.connect()
    await broker.submit_order(
        OrderRequest(
            order_id="phase6-paper-order",
            client_order_id="phase6-paper-client",
            symbol=candles[0].symbol,
            venue=candles[0].venue,
            side=Side.BUY,
            quantity=Decimal(2),
            created_at=candles[1].close_time,
        )
    )
    fills = await broker.on_candle(candles[2])
    await broker.disconnect()
    if len(fills) != 1:
        raise RuntimeError("Phase 6 parity fixture did not produce one paper fill")
    return fills[0], broker.execution_model


def _future_signal_is_blocked(candles: tuple[NormalizedCandle, ...]) -> bool:
    engine = BacktestEngine(
        _pipeline(_FutureDatedStrategy()),
        starting_cash=Decimal(10000),
        requested_quantity=Decimal(1),
    )
    try:
        engine.run(list(candles))
    except ValueError as exc:
        return "after the latest closed candle" in str(exc)
    return False


def _out_of_order_is_blocked(candles: tuple[NormalizedCandle, ...]) -> bool:
    engine = BacktestEngine(
        _pipeline(_OneShotStrategy()),
        starting_cash=Decimal(10000),
        requested_quantity=Decimal(1),
    )
    try:
        engine.run([candles[1], candles[0], candles[2]])
    except ValueError as exc:
        return "strictly increasing" in str(exc)
    return False


def write_backtest_artifacts(root: Path) -> None:
    root = root.resolve()
    report, bias = build_backtest_artifacts()
    _write_json(root / BACKTEST_REPORT, report)
    _write_json(root / BIAS_REPORT, bias)
    records = build_sequential_phase_records(
        root,
        {
            0: PHASE_ZERO_EVIDENCE,
            1: PHASE_ONE_EVIDENCE,
            2: PHASE_TWO_EVIDENCE,
            3: PHASE_THREE_EVIDENCE,
            4: PHASE_FOUR_EVIDENCE,
            5: PHASE_FIVE_EVIDENCE,
            6: PHASE_SIX_EVIDENCE,
        },
    )
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_backtest_artifacts(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    report, bias = build_backtest_artifacts()
    expected = {
        BACKTEST_REPORT: _pretty_json(report),
        BIAS_REPORT: _pretty_json(bias),
    }
    errors: list[str] = []
    for relative, content in expected.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing Phase 6 evidence: {relative.as_posix()}")
        elif path.read_text(encoding="utf-8") != content:
            errors.append(f"stale Phase 6 evidence: {relative.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 6):
        errors.append("Phase 6 is not PASS in the governance ledger")
    return tuple(errors)


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-6 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_backtest_artifacts(root)
        print("Phase 6: PASS")
        return 0
    errors = check_backtest_artifacts(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 6 backtest artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
