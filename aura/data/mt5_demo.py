from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from aura.data.mt5_contracts import MT5AccountState, MT5UniverseDiscovery
from aura.domain.models import NormalizedCandle
from aura.execution.demo_guard import DemoExecutionGuard


@dataclass(slots=True, frozen=True)
class MT5DemoCredentials:
    login: int
    password: str
    server: str
    terminal_path: str | None = None

    def __post_init__(self) -> None:
        if self.login <= 0:
            raise ValueError("MT5 login must be positive")
        if not self.password or not self.server:
            raise ValueError("MT5 demo password and server are required")


def load_mt5_demo_credentials_from_env() -> MT5DemoCredentials:
    login = os.environ.get("AURA_MT5_DEMO_LOGIN", "").strip()
    password = os.environ.get("AURA_MT5_DEMO_PASSWORD", "")
    server = os.environ.get("AURA_MT5_DEMO_SERVER", "").strip()
    path = os.environ.get("AURA_MT5_TERMINAL_PATH", "").strip() or None
    if not login or not password or not server:
        raise RuntimeError(
            "set AURA_MT5_DEMO_LOGIN, AURA_MT5_DEMO_PASSWORD and AURA_MT5_DEMO_SERVER"
        )
    return MT5DemoCredentials(
        login=int(login),
        password=password,
        server=server,
        terminal_path=path,
    )


class OfficialMT5Gateway:
    """Guarded wrapper around MetaQuotes' official `MetaTrader5` Python package.

    The package is imported only on the terminal host, keeping Linux CI portable.
    Trading, margin and profit calls are unavailable until `connect_demo` verifies
    the account as DEMO. This prevents an accidentally configured real terminal
    from being reached by AURA's demo/evolution runtime.
    """

    def __init__(self, module: Any | None = None) -> None:
        self._mt5 = module
        self._demo_verified = False

    @property
    def module(self) -> Any:
        if self._mt5 is None:
            try:
                self._mt5 = importlib.import_module("MetaTrader5")
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "MetaTrader5 package is required on the Windows/MT5 terminal host"
                ) from exc
        return self._mt5

    @property
    def demo_verified(self) -> bool:
        return self._demo_verified

    def connect_demo(self, credentials: MT5DemoCredentials) -> MT5AccountState:
        mt5 = self.module
        if credentials.terminal_path:
            ok = mt5.initialize(
                credentials.terminal_path,
                login=credentials.login,
                password=credentials.password,
                server=credentials.server,
            )
        else:
            ok = mt5.initialize(
                login=credentials.login,
                password=credentials.password,
                server=credentials.server,
            )
        if not ok:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        info = mt5.account_info()
        if info is None:
            mt5.shutdown()
            raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")
        try:
            DemoExecutionGuard.assert_mt5_demo_account(info)
        except Exception:
            mt5.shutdown()
            raise
        self._demo_verified = True
        source = info._asdict() if hasattr(info, "_asdict") else vars(info)
        margin_level = source.get("margin_level")
        return MT5AccountState(
            login=int(source["login"]),
            server=str(source["server"]),
            currency=str(source["currency"]),
            balance=Decimal(str(source["balance"])),
            equity=Decimal(str(source["equity"])),
            margin=Decimal(str(source["margin"])),
            margin_free=Decimal(str(source["margin_free"])),
            margin_level=Decimal(str(margin_level)) if margin_level is not None else None,
        )

    def initialize(self) -> bool:
        return bool(self.module.initialize())

    def shutdown(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
        self._demo_verified = False

    def symbols_get(self) -> tuple[Any, ...] | None:
        return self.module.symbols_get()

    def symbol_info(self, symbol: str) -> Any | None:
        return self.module.symbol_info(symbol)

    def symbol_info_tick(self, symbol: str) -> Any | None:
        return self.module.symbol_info_tick(symbol)

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        return bool(self.module.symbol_select(symbol, enable))

    def copy_rates_from_pos(
        self,
        symbol: str,
        timeframe: int,
        start_pos: int,
        count: int,
    ) -> Any:
        return self.module.copy_rates_from_pos(symbol, timeframe, start_pos, count)

    def orders_get(self, **kwargs: Any) -> tuple[Any, ...] | None:
        return self.module.orders_get(**kwargs)

    def positions_get(self, **kwargs: Any) -> tuple[Any, ...] | None:
        return self.module.positions_get(**kwargs)

    def history_deals_get(self, *args: Any, **kwargs: Any) -> tuple[Any, ...] | None:
        return self.module.history_deals_get(*args, **kwargs)

    def account_info(self) -> Any | None:
        return self.module.account_info()

    def terminal_info(self) -> Any | None:
        return self.module.terminal_info()

    def order_calc_margin(
        self,
        action: int,
        symbol: str,
        volume: float,
        price: float,
    ) -> float | None:
        self._require_demo_verified()
        return self.module.order_calc_margin(action, symbol, volume, price)

    def order_calc_profit(
        self,
        action: int,
        symbol: str,
        volume: float,
        price_open: float,
        price_close: float,
    ) -> float | None:
        self._require_demo_verified()
        return self.module.order_calc_profit(
            action,
            symbol,
            volume,
            price_open,
            price_close,
        )

    def order_check(self, request: dict[str, Any]) -> Any:
        self._require_demo_verified()
        return self.module.order_check(request)

    def order_send(self, request: dict[str, Any]) -> Any:
        self._require_demo_verified()
        return self.module.order_send(request)

    def last_error(self) -> Any:
        return self.module.last_error()

    def constant(self, name: str) -> int:
        return int(getattr(self.module, name))

    def discover_universe(self):
        return MT5UniverseDiscovery(self).discover()

    def _require_demo_verified(self) -> None:
        if not self._demo_verified:
            raise RuntimeError("MT5 trading call blocked until DEMO account verification succeeds")


_TIMEFRAME_CONSTANTS = {
    "1m": "TIMEFRAME_M1",
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}

_TIMEFRAME_DURATION = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


class MT5DemoClosedCandleSource:
    """Read only fully closed candles from the connected MT5 demo terminal."""

    def __init__(self, gateway: OfficialMT5Gateway, *, venue: str = "EXNESS_MT5_DEMO") -> None:
        self.gateway = gateway
        self.venue = venue

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        *,
        count: int = 500,
    ) -> tuple[NormalizedCandle, ...]:
        if count <= 0:
            raise ValueError("count must be positive")
        try:
            constant_name = _TIMEFRAME_CONSTANTS[timeframe]
            duration = _TIMEFRAME_DURATION[timeframe]
        except KeyError as exc:
            raise ValueError(f"unsupported MT5 timeframe: {timeframe}") from exc

        rows = self.gateway.copy_rates_from_pos(
            symbol,
            self.gateway.constant(constant_name),
            1,
            count,
        )
        if rows is None:
            raise RuntimeError(
                f"MT5 copy_rates_from_pos failed for {symbol}/{timeframe}: "
                f"{self.gateway.last_error()}"
            )

        candles: list[NormalizedCandle] = []
        for row in rows:
            open_time = datetime.fromtimestamp(int(_field(row, "time")), tz=UTC)
            real_volume = Decimal(str(_field(row, "real_volume", fallback=0)))
            tick_volume = Decimal(str(_field(row, "tick_volume", fallback=0)))
            volume = real_volume if real_volume > 0 else tick_volume
            candles.append(
                NormalizedCandle(
                    symbol=symbol,
                    venue=self.venue,
                    timeframe=timeframe,
                    open_time=open_time,
                    close_time=open_time + duration,
                    open=Decimal(str(_field(row, "open"))),
                    high=Decimal(str(_field(row, "high"))),
                    low=Decimal(str(_field(row, "low"))),
                    close=Decimal(str(_field(row, "close"))),
                    volume=volume,
                    closed=True,
                )
            )
        candles.sort(key=lambda candle: candle.open_time)
        return tuple(candles)


def _field(row: Any, name: str, fallback: Any | None = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, fallback)
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, fallback)
