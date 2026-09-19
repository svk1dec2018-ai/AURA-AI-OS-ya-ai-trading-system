from __future__ import annotations

import os
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MarketFamily(str, Enum):
    FOREX = "FOREX"
    COMMODITIES = "COMMODITIES"
    GLOBAL_INDICES = "GLOBAL_INDICES"
    INDIA_EQUITIES = "INDIA_EQUITIES"
    INDIA_FUTURES_OPTIONS = "INDIA_FUTURES_OPTIONS"
    CRYPTO_SPOT = "CRYPTO_SPOT"
    CRYPTO_DERIVATIVES = "CRYPTO_DERIVATIVES"


class ProviderSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    families: tuple[MarketFamily, ...]
    credential_env: tuple[str, ...] = ()
    read_only_without_credentials: bool = False
    execution_supported: bool = False
    execution_default_enabled: bool = False

    def configured(self) -> bool:
        return all(bool(os.environ.get(name, "").strip()) for name in self.credential_env)

    def missing_credentials(self) -> tuple[str, ...]:
        return tuple(
            name for name in self.credential_env if not os.environ.get(name, "").strip()
        )

    def status(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "families": [item.value for item in self.families],
            "configured": self.configured(),
            "missing_credentials": list(self.missing_credentials()),
            "read_only_without_credentials": self.read_only_without_credentials,
            "execution_supported": self.execution_supported,
            "execution_default_enabled": self.execution_default_enabled,
        }


MARKET_PROVIDERS: dict[str, ProviderSpec] = {
    "mt5": ProviderSpec(
        key="mt5",
        name="MetaTrader 5",
        families=(
            MarketFamily.FOREX,
            MarketFamily.COMMODITIES,
            MarketFamily.GLOBAL_INDICES,
            MarketFamily.CRYPTO_DERIVATIVES,
        ),
        credential_env=(),
        read_only_without_credentials=True,
        execution_supported=True,
        execution_default_enabled=False,
    ),
    "dhan": ProviderSpec(
        key="dhan",
        name="Dhan",
        families=(MarketFamily.INDIA_EQUITIES, MarketFamily.INDIA_FUTURES_OPTIONS),
        credential_env=("AURA_DHAN_CLIENT_ID", "AURA_DHAN_ACCESS_TOKEN"),
        execution_supported=True,
        execution_default_enabled=False,
    ),
    "angel_one": ProviderSpec(
        key="angel_one",
        name="Angel One SmartAPI",
        families=(MarketFamily.INDIA_EQUITIES, MarketFamily.INDIA_FUTURES_OPTIONS),
        credential_env=(
            "AURA_ANGEL_API_KEY",
            "AURA_ANGEL_CLIENT_CODE",
            "AURA_ANGEL_PASSWORD",
            "AURA_ANGEL_TOTP_SECRET",
        ),
        execution_supported=True,
        execution_default_enabled=False,
    ),
    "binance": ProviderSpec(
        key="binance",
        name="Binance",
        families=(MarketFamily.CRYPTO_SPOT, MarketFamily.CRYPTO_DERIVATIVES),
        credential_env=("AURA_BINANCE_API_KEY", "AURA_BINANCE_API_SECRET"),
        read_only_without_credentials=True,
        execution_supported=True,
        execution_default_enabled=False,
    ),
    "kraken": ProviderSpec(
        key="kraken",
        name="Kraken",
        families=(MarketFamily.CRYPTO_SPOT, MarketFamily.CRYPTO_DERIVATIVES),
        credential_env=("AURA_KRAKEN_API_KEY", "AURA_KRAKEN_API_SECRET"),
        read_only_without_credentials=True,
        execution_supported=True,
        execution_default_enabled=False,
    ),
    "oanda": ProviderSpec(
        key="oanda",
        name="OANDA",
        families=(MarketFamily.FOREX, MarketFamily.COMMODITIES, MarketFamily.GLOBAL_INDICES),
        credential_env=("AURA_OANDA_ACCOUNT_ID", "AURA_OANDA_TOKEN"),
        execution_supported=True,
        execution_default_enabled=False,
    ),
}


def provider_status() -> tuple[dict[str, object], ...]:
    return tuple(MARKET_PROVIDERS[key].status() for key in sorted(MARKET_PROVIDERS))


def supported_market_families() -> tuple[str, ...]:
    return tuple(item.value for item in MarketFamily)
