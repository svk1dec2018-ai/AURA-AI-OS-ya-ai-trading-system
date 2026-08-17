from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from aura.data.mt5_demo import (
    MT5DemoClosedCandleSource,
    OfficialMT5Gateway,
)
from aura.domain.models import NormalizedCandle


_DEFAULT_POLL_SECONDS = {
    "1m": 5.0,
    "5m": 15.0,
    "15m": 30.0,
    "30m": 60.0,
    "1h": 120.0,
    "4h": 300.0,
    "1d": 600.0,
}


@dataclass(slots=True, frozen=True)
class MT5PollingPolicy:
    timeframes: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
    seed_bars: int = 250
    catchup_bars: int = 3
    idle_sleep_seconds: float = 1.0
    poll_seconds: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_POLL_SECONDS))

    def __post_init__(self) -> None:
        if not self.timeframes:
            raise ValueError("at least one MT5 polling timeframe is required")
        if len(self.timeframes) != len(set(self.timeframes)):
            raise ValueError("MT5 polling timeframes must be unique")
        if self.seed_bars <= 0 or self.catchup_bars <= 0:
            raise ValueError("MT5 seed/catchup bars must be positive")
        if self.idle_sleep_seconds <= 0:
            raise ValueError("idle_sleep_seconds must be positive")
        missing = set(self.timeframes) - set(self.poll_seconds)
        if missing:
            raise ValueError(f"missing polling cadence for: {', '.join(sorted(missing))}")
        if any(self.poll_seconds[item] <= 0 for item in self.timeframes):
            raise ValueError("MT5 polling cadences must be positive")


@dataclass(slots=True, frozen=True)
class MT5PollingIssue:
    symbol: str
    timeframe: str
    detail: str


@dataclass(slots=True, frozen=True)
class MT5SeedResult:
    histories: dict[tuple[str, str], tuple[NormalizedCandle, ...]]
    issues: tuple[MT5PollingIssue, ...]


class MT5DemoPollingSource:
    """Poll enabled MT5 demo symbols and cache point-in-time execution metadata."""

    def __init__(
        self,
        gateway: OfficialMT5Gateway,
        symbols: tuple[str, ...] | list[str],
        *,
        policy: MT5PollingPolicy | None = None,
        venue: str = "EXNESS_MT5_DEMO",
    ) -> None:
        unique_symbols = tuple(sorted(set(symbols)))
        if not unique_symbols:
            raise ValueError("MT5 polling source requires at least one symbol")
        if not gateway.demo_verified:
            raise RuntimeError("MT5 polling source requires a verified DEMO gateway")
        self.gateway = gateway
        self.symbols = unique_symbols
        self.policy = policy or MT5PollingPolicy()
        self.candles = MT5DemoClosedCandleSource(gateway, venue=venue)
        self._last_close: dict[tuple[str, str], datetime] = {}
        self._next_due: dict[str, float] = {
            timeframe: 0.0 for timeframe in self.policy.timeframes
        }
        self._execution_quality: dict[str, dict[str, Any]] = {}
        self._last_issues: tuple[MT5PollingIssue, ...] = ()
        self._stopped = False

    @property
    def last_issues(self) -> tuple[MT5PollingIssue, ...]:
        return self._last_issues

    def metadata_for(self, symbol: str) -> dict[str, Any]:
        snapshot = self._execution_quality.get(symbol)
        return {"execution_quality": dict(snapshot)} if snapshot is not None else {}

    def stop(self) -> None:
        self._stopped = True

    async def seed_histories(self) -> MT5SeedResult:
        result = await asyncio.to_thread(self._seed_sync)
        for key, history in result.histories.items():
            if history:
                self._last_close[key] = history[-1].close_time
        self._last_issues = result.issues
        return result

    async def batches(self):
        """Yield newly closed candle batches indefinitely until `stop()` is called."""
        while not self._stopped:
            now = time.monotonic()
            due = tuple(
                timeframe
                for timeframe in self.policy.timeframes
                if now >= self._next_due[timeframe]
            )
            if not due:
                await asyncio.sleep(self.policy.idle_sleep_seconds)
                continue

            for timeframe in due:
                self._next_due[timeframe] = now + self.policy.poll_seconds[timeframe]
            grouped, issues = await asyncio.to_thread(self._poll_sync, due)
            self._last_issues = issues
            for close_time in sorted(grouped):
                batch = tuple(
                    sorted(
                        grouped[close_time],
                        key=lambda item: (item.symbol, item.timeframe),
                    )
                )
                if batch:
                    yield batch
            await asyncio.sleep(self.policy.idle_sleep_seconds)

    def _seed_sync(self) -> MT5SeedResult:
        histories: dict[tuple[str, str], tuple[NormalizedCandle, ...]] = {}
        issues: list[MT5PollingIssue] = []
        for symbol in self.symbols:
            self._refresh_execution_quality(symbol)
            for timeframe in self.policy.timeframes:
                try:
                    history = self.candles.fetch(
                        symbol,
                        timeframe,
                        count=self.policy.seed_bars,
                    )
                except Exception as exc:  # noqa: BLE001 - isolate inactive symbol/timeframe
                    issues.append(
                        MT5PollingIssue(
                            symbol=symbol,
                            timeframe=timeframe,
                            detail=f"{type(exc).__name__}: {exc}",
                        )
                    )
                    continue
                if history:
                    histories[(symbol, timeframe)] = history
        return MT5SeedResult(histories=histories, issues=tuple(issues))

    def _poll_sync(
        self,
        timeframes: tuple[str, ...],
    ) -> tuple[dict[datetime, list[NormalizedCandle]], tuple[MT5PollingIssue, ...]]:
        grouped: dict[datetime, list[NormalizedCandle]] = {}
        issues: list[MT5PollingIssue] = []
        for symbol in self.symbols:
            self._refresh_execution_quality(symbol)
            for timeframe in timeframes:
                key = (symbol, timeframe)
                try:
                    candles = self.candles.fetch(
                        symbol,
                        timeframe,
                        count=self.policy.catchup_bars,
                    )
                except Exception as exc:  # noqa: BLE001 - isolate one market-data failure
                    issues.append(
                        MT5PollingIssue(
                            symbol=symbol,
                            timeframe=timeframe,
                            detail=f"{type(exc).__name__}: {exc}",
                        )
                    )
                    continue
                previous = self._last_close.get(key)
                fresh = [
                    candle
                    for candle in candles
                    if previous is None or candle.close_time > previous
                ]
                if not fresh:
                    continue
                for candle in fresh:
                    grouped.setdefault(candle.close_time, []).append(candle)
                self._last_close[key] = fresh[-1].close_time
        return grouped, tuple(issues)

    def _refresh_execution_quality(self, symbol: str) -> None:
        try:
            raw = self.gateway.symbol_info_tick(symbol)
        except Exception:  # noqa: BLE001 - execution advisory may remain unavailable
            return
        if raw is None:
            return
        source = _asdict(raw)
        bid = Decimal(str(source.get("bid", 0)))
        ask = Decimal(str(source.get("ask", 0)))
        if bid <= 0 or ask <= 0 or ask < bid:
            return
        midpoint = (bid + ask) / Decimal(2)
        spread_bps = float((ask - bid) / midpoint * Decimal(10000))
        observed_at = _tick_timestamp(source)
        self._execution_quality[symbol] = {
            "source_id": f"mt5:{symbol}:bid-ask",
            "observed_at": observed_at.isoformat(),
            "spread_bps": spread_bps,
            "estimated_slippage_bps": spread_bps / 2.0,
            "top_of_book_notional": 0.0,
            "trust_score": 1.0,
        }


def _asdict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    return dict(vars(value))


def _tick_timestamp(source: dict[str, Any]) -> datetime:
    if source.get("time_msc"):
        return datetime.fromtimestamp(int(source["time_msc"]) / 1000, tz=UTC)
    if source.get("time"):
        return datetime.fromtimestamp(int(source["time"]), tz=UTC)
    return datetime.now(UTC)
