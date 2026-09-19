from __future__ import annotations

from enum import Enum
from typing import Any
from urllib.parse import urlparse


class LiveTradingDisabledError(RuntimeError):
    pass


class DemoVenue(str, Enum):
    PAPER = "paper"
    MT5_DEMO = "mt5_demo"
    DHAN_SANDBOX = "dhan_sandbox"
    BINANCE_TESTNET = "binance_testnet"


class DemoExecutionGuard:
    """Fail-closed protection: AURA demo/evolution runtimes cannot reach real money."""

    MT5_DEMO_TRADE_MODE = 0
    DHAN_SANDBOX_HOST = "sandbox.dhan.co"
    BINANCE_TESTNET_HOSTS = frozenset(
        {"testnet.binance.vision", "stream.testnet.binance.vision"}
    )

    @classmethod
    def assert_mt5_demo_account(cls, account_info: Any) -> None:
        source = (
            account_info._asdict()
            if hasattr(account_info, "_asdict")
            else account_info
            if isinstance(account_info, dict)
            else vars(account_info)
        )
        trade_mode = int(source.get("trade_mode", -1))
        if trade_mode != cls.MT5_DEMO_TRADE_MODE:
            raise LiveTradingDisabledError(
                f"MT5 account trade_mode={trade_mode} is not DEMO; real/contest trading blocked"
            )
        if not bool(source.get("trade_allowed", True)):
            raise LiveTradingDisabledError("MT5 demo account does not allow trading")
        if not bool(source.get("trade_expert", True)):
            raise LiveTradingDisabledError("MT5 demo account blocks expert/API trading")

    @classmethod
    def assert_dhan_sandbox_url(cls, base_url: str) -> None:
        host = (urlparse(base_url).hostname or "").lower()
        if host != cls.DHAN_SANDBOX_HOST:
            raise LiveTradingDisabledError(
                f"Dhan demo runtime only permits {cls.DHAN_SANDBOX_HOST}; got {host or 'invalid URL'}"
            )

    @classmethod
    def assert_binance_testnet_url(cls, base_url: str) -> None:
        host = (urlparse(base_url).hostname or "").lower()
        if host not in cls.BINANCE_TESTNET_HOSTS:
            raise LiveTradingDisabledError(
                f"Binance demo runtime only permits testnet hosts; got {host or 'invalid URL'}"
            )

    @classmethod
    def assert_demo_venue(
        cls,
        venue: DemoVenue,
        *,
        account_info: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        if venue == DemoVenue.PAPER:
            return
        if venue == DemoVenue.MT5_DEMO:
            if account_info is None:
                raise LiveTradingDisabledError("MT5 demo verification requires account_info")
            cls.assert_mt5_demo_account(account_info)
            return
        if venue == DemoVenue.DHAN_SANDBOX:
            if base_url is None:
                raise LiveTradingDisabledError("Dhan sandbox verification requires base_url")
            cls.assert_dhan_sandbox_url(base_url)
            return
        if venue == DemoVenue.BINANCE_TESTNET:
            if base_url is None:
                raise LiveTradingDisabledError("Binance testnet verification requires base_url")
            cls.assert_binance_testnet_url(base_url)
            return
        raise LiveTradingDisabledError(f"unsupported demo venue: {venue}")
