from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from aura.data.mt5_demo import (
    MT5DemoClosedCandleSource,
    OfficialMT5Gateway,
    load_mt5_demo_credentials_from_env,
)
from aura.execution.demo_guard import DemoExecutionGuard


@dataclass(slots=True, frozen=True)
class ReadinessCheck:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True, frozen=True)
class MT5DemoReadinessReport:
    requested_symbol: str
    resolved_symbol: str | None
    server: str | None
    checks: tuple[ReadinessCheck, ...]
    order_submission_attempted: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "requested_symbol": self.requested_symbol,
            "resolved_symbol": self.resolved_symbol,
            "server": self.server,
            "order_submission_attempted": self.order_submission_attempted,
            "checks": [asdict(check) for check in self.checks],
        }


def resolve_xauusd_symbol(
    gateway: OfficialMT5Gateway,
    *,
    preferred_symbol: str = "XAUUSD",
) -> str:
    """Resolve a broker-specific XAUUSD/Gold symbol conservatively.

    Brokers can expose suffixes such as XAUUSDm or XAUUSD.a. Exact XAUUSD is
    preferred when tradable; otherwise a tradable XAUUSD-prefixed variant is
    preferred over a generic GOLD-labelled symbol.
    """

    rows = gateway.symbols_get()
    if rows is None:
        raise RuntimeError(f"MT5 symbols_get failed: {gateway.last_error()}")

    preferred = preferred_symbol.upper()
    candidates: list[tuple[int, str]] = []
    for row in rows:
        source = _asdict(row)
        name = str(source.get("name", "")).strip()
        if not name:
            continue
        upper_name = name.upper()
        compact_name = re.sub(r"[^A-Z0-9]", "", upper_name)
        text = " ".join(
            (
                upper_name,
                str(source.get("description", "")).upper(),
                str(source.get("path", "")).upper(),
            )
        )
        trade_mode = int(source.get("trade_mode", 0))
        tradable_bonus = 30 if trade_mode != 0 else 0

        score = -1
        if upper_name == preferred:
            score = 120
        elif compact_name.startswith(preferred):
            score = 100
        elif "XAUUSD" in compact_name:
            score = 90
        elif "GOLD" in text or "XAU" in text:
            score = 60
        if score >= 0:
            candidates.append((score + tradable_bonus, name))

    if not candidates:
        raise RuntimeError("No XAUUSD/Gold symbol was found in the connected MT5 account")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def inspect_mt5_demo_readiness(
    gateway: OfficialMT5Gateway,
    *,
    preferred_symbol: str = "XAUUSD",
) -> MT5DemoReadinessReport:
    """Perform a read-only/no-order readiness check for an MT5 DEMO XAUUSD host."""

    checks: list[ReadinessCheck] = []
    resolved_symbol: str | None = None
    server: str | None = None

    account_info = gateway.account_info()
    if account_info is None:
        return _report(
            preferred_symbol,
            None,
            None,
            checks,
            "demo-account",
            False,
            f"account_info failed: {gateway.last_error()}",
        )
    account = _asdict(account_info)
    server = str(account.get("server", "")) or None
    try:
        DemoExecutionGuard.assert_mt5_demo_account(account_info)
    except RuntimeError as exc:
        return _report(
            preferred_symbol,
            None,
            server,
            checks,
            "demo-account",
            False,
            str(exc),
        )
    checks.append(ReadinessCheck("demo-account", True, "verified MT5 DEMO account"))

    terminal_info = gateway.terminal_info()
    if terminal_info is None:
        return _report(
            preferred_symbol,
            None,
            server,
            checks,
            "terminal-connected",
            False,
            f"terminal_info failed: {gateway.last_error()}",
        )
    terminal = _asdict(terminal_info)
    if not bool(terminal.get("connected", False)):
        return _report(
            preferred_symbol,
            None,
            server,
            checks,
            "terminal-connected",
            False,
            "MetaTrader 5 terminal is not connected to the broker",
        )
    checks.append(ReadinessCheck("terminal-connected", True, "MT5 terminal is connected"))

    try:
        resolved_symbol = resolve_xauusd_symbol(
            gateway,
            preferred_symbol=preferred_symbol,
        )
    except RuntimeError as exc:
        return _report(
            preferred_symbol,
            None,
            server,
            checks,
            "xauusd-symbol",
            False,
            str(exc),
        )
    checks.append(
        ReadinessCheck(
            "xauusd-symbol",
            True,
            f"resolved {preferred_symbol} to broker symbol {resolved_symbol}",
        )
    )

    raw_symbol = gateway.symbol_info(resolved_symbol)
    if raw_symbol is None:
        return _report(
            preferred_symbol,
            resolved_symbol,
            server,
            checks,
            "symbol-metadata",
            False,
            f"symbol_info failed for {resolved_symbol}",
        )
    symbol = _asdict(raw_symbol)
    if int(symbol.get("trade_mode", 0)) == 0:
        return _report(
            preferred_symbol,
            resolved_symbol,
            server,
            checks,
            "symbol-metadata",
            False,
            f"{resolved_symbol} is disabled/non-tradable on this DEMO account",
        )
    minimum = Decimal(str(symbol.get("volume_min", 0)))
    step = Decimal(str(symbol.get("volume_step", 0)))
    maximum = Decimal(str(symbol.get("volume_max", 0)))
    if minimum <= 0 or step <= 0 or maximum <= 0:
        return _report(
            preferred_symbol,
            resolved_symbol,
            server,
            checks,
            "symbol-metadata",
            False,
            "invalid volume_min/volume_step/volume_max metadata",
        )
    if not bool(symbol.get("visible", True)) and not gateway.symbol_select(resolved_symbol, True):
        return _report(
            preferred_symbol,
            resolved_symbol,
            server,
            checks,
            "symbol-metadata",
            False,
            f"could not enable {resolved_symbol} in Market Watch",
        )
    checks.append(
        ReadinessCheck(
            "symbol-metadata",
            True,
            f"tradable; min={minimum} step={step} max={maximum}",
        )
    )

    tick = gateway.symbol_info_tick(resolved_symbol)
    if tick is None:
        return _report(
            preferred_symbol,
            resolved_symbol,
            server,
            checks,
            "live-tick",
            False,
            f"no live tick for {resolved_symbol}",
        )
    tick_data = _asdict(tick)
    bid = Decimal(str(tick_data.get("bid", 0)))
    ask = Decimal(str(tick_data.get("ask", 0)))
    if bid <= 0 or ask <= 0 or ask < bid:
        return _report(
            preferred_symbol,
            resolved_symbol,
            server,
            checks,
            "live-tick",
            False,
            f"invalid bid/ask for {resolved_symbol}: bid={bid} ask={ask}",
        )
    checks.append(ReadinessCheck("live-tick", True, f"bid={bid} ask={ask}"))

    try:
        candles = MT5DemoClosedCandleSource(gateway).fetch(
            resolved_symbol,
            "1m",
            count=2,
        )
    except (RuntimeError, ValueError) as exc:
        return _report(
            preferred_symbol,
            resolved_symbol,
            server,
            checks,
            "closed-candle",
            False,
            str(exc),
        )
    if not candles or not all(candle.closed for candle in candles):
        return _report(
            preferred_symbol,
            resolved_symbol,
            server,
            checks,
            "closed-candle",
            False,
            "no fully closed 1m candles were returned",
        )
    checks.append(
        ReadinessCheck(
            "closed-candle",
            True,
            f"received {len(candles)} fully closed 1m candles",
        )
    )

    return MT5DemoReadinessReport(
        requested_symbol=preferred_symbol,
        resolved_symbol=resolved_symbol,
        server=server,
        checks=tuple(checks),
        order_submission_attempted=False,
    )


def _report(
    requested_symbol: str,
    resolved_symbol: str | None,
    server: str | None,
    checks: list[ReadinessCheck],
    name: str,
    passed: bool,
    detail: str,
) -> MT5DemoReadinessReport:
    checks.append(ReadinessCheck(name, passed, detail))
    return MT5DemoReadinessReport(
        requested_symbol=requested_symbol,
        resolved_symbol=resolved_symbol,
        server=server,
        checks=tuple(checks),
        order_submission_attempted=False,
    )


def _asdict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    return dict(vars(value))


def main() -> int:
    gateway = OfficialMT5Gateway()
    try:
        credentials = load_mt5_demo_credentials_from_env()
        gateway.connect_demo(credentials)
        report = inspect_mt5_demo_readiness(gateway)
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0 if report.ready else 2
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        safe_error = {
            "ready": False,
            "order_submission_attempted": False,
            "error": str(exc),
        }
        print(json.dumps(safe_error, indent=2, sort_keys=True))
        return 2
    finally:
        gateway.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
