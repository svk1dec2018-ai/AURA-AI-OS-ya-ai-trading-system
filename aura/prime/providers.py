from __future__ import annotations

import os
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ProviderReadiness(str, Enum):
    PUBLIC_READY = "PUBLIC_READY"
    CONFIG_REQUIRED = "CONFIG_REQUIRED"
    DATA_ONLY = "DATA_ONLY"
    DEMO_EXECUTION = "DEMO_EXECUTION"
    LIVE_GATED = "LIVE_GATED"


class PrimeProvider(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    markets: tuple[str, ...]
    free_first: bool
    public_no_key: bool = False
    required_env: tuple[str, ...] = ()
    data_supported: bool = True
    demo_execution_supported: bool = False
    live_execution_certified: bool = False
    notes: tuple[str, ...] = ()

    def configured(self) -> bool:
        return all(bool(os.environ.get(name, "").strip()) for name in self.required_env)

    def missing_env(self) -> tuple[str, ...]:
        return tuple(name for name in self.required_env if not os.environ.get(name, "").strip())

    def readiness(self) -> ProviderReadiness:
        if self.live_execution_certified:
            return ProviderReadiness.LIVE_GATED
        if self.demo_execution_supported:
            return (
                ProviderReadiness.DEMO_EXECUTION
                if self.configured()
                else ProviderReadiness.CONFIG_REQUIRED
            )
        if self.public_no_key:
            return ProviderReadiness.PUBLIC_READY
        if self.required_env and not self.configured():
            return ProviderReadiness.CONFIG_REQUIRED
        return ProviderReadiness.DATA_ONLY


PRIME_PROVIDERS: dict[str, PrimeProvider] = {
    "mt5": PrimeProvider(
        provider_id="mt5",
        display_name="MetaTrader 5",
        markets=("FOREX", "METALS", "ENERGY", "GLOBAL_INDICES", "CFD", "CRYPTO_CFD"),
        free_first=True,
        required_env=(
            "AURA_MT5_DEMO_LOGIN",
            "AURA_MT5_DEMO_PASSWORD",
            "AURA_MT5_DEMO_SERVER",
        ),
        demo_execution_supported=True,
        notes=("DEMO execution is protected; live money remains governance-gated.",),
    ),
    "coinbase": PrimeProvider(
        provider_id="coinbase",
        display_name="Coinbase Public",
        markets=("CRYPTO",),
        free_first=True,
        public_no_key=True,
        notes=("Public market-data route; no trading authority.",),
    ),
    "kraken": PrimeProvider(
        provider_id="kraken",
        display_name="Kraken Public",
        markets=("CRYPTO",),
        free_first=True,
        public_no_key=True,
        notes=("Public OHLC route is key-free; authenticated execution is not certified.",),
    ),
    "bybit": PrimeProvider(
        provider_id="bybit",
        display_name="Bybit Public",
        markets=("CRYPTO",),
        free_first=True,
        public_no_key=True,
    ),
    "okx": PrimeProvider(
        provider_id="okx",
        display_name="OKX Public",
        markets=("CRYPTO",),
        free_first=True,
        public_no_key=True,
    ),
    "dhan": PrimeProvider(
        provider_id="dhan",
        display_name="Dhan",
        markets=("NSE", "BSE", "NFO", "BFO", "MCX"),
        free_first=False,
        required_env=("AURA_DHAN_CLIENT_ID", "AURA_DHAN_ACCESS_TOKEN"),
        notes=("Official data access depends on account/subscription terms.",),
    ),
    "angel_one": PrimeProvider(
        provider_id="angel_one",
        display_name="Angel One SmartAPI",
        markets=("NSE", "BSE", "NFO", "BFO", "MCX"),
        free_first=True,
        required_env=(
            "AURA_ANGEL_ONE_API_KEY",
            "AURA_ANGEL_ONE_CLIENT_CODE",
            "AURA_ANGEL_ONE_JWT_TOKEN",
            "AURA_ANGEL_ONE_REFRESH_TOKEN",
        ),
        notes=("Read-only/reconciliation path implemented; order mutation remains gated.",),
    ),
    "shoonya": PrimeProvider(
        provider_id="shoonya",
        display_name="Shoonya",
        markets=("NSE", "BSE", "NFO", "CDS", "MCX"),
        free_first=True,
        required_env=(
            "AURA_SHOONYA_USER_ID",
            "AURA_SHOONYA_ACCOUNT_ID",
            "AURA_SHOONYA_SESSION_TOKEN",
        ),
    ),
    "flattrade": PrimeProvider(
        provider_id="flattrade",
        display_name="Flattrade",
        markets=("NSE", "BSE", "NFO", "CDS", "MCX"),
        free_first=True,
        required_env=(
            "AURA_FLATTRADE_USER_ID",
            "AURA_FLATTRADE_ACCOUNT_ID",
            "AURA_FLATTRADE_ACCESS_TOKEN",
        ),
    ),
    "oanda": PrimeProvider(
        provider_id="oanda",
        display_name="OANDA",
        markets=("FOREX", "CFD"),
        free_first=True,
        required_env=("AURA_OANDA_ACCOUNT_ID", "AURA_OANDA_ACCESS_TOKEN"),
        notes=("Current AURA route is market-data/read-only.",),
    ),
    "gdelt": PrimeProvider(
        provider_id="gdelt",
        display_name="GDELT",
        markets=("GLOBAL_NEWS",),
        free_first=True,
        public_no_key=True,
        data_supported=True,
    ),
    "sec": PrimeProvider(
        provider_id="sec",
        display_name="SEC EDGAR",
        markets=("US_FUNDAMENTALS",),
        free_first=True,
        public_no_key=True,
        data_supported=True,
    ),
}


def provider_matrix() -> tuple[dict[str, object], ...]:
    rows = []
    for key in sorted(PRIME_PROVIDERS):
        provider = PRIME_PROVIDERS[key]
        rows.append(
            {
                "provider_id": provider.provider_id,
                "display_name": provider.display_name,
                "markets": list(provider.markets),
                "free_first": provider.free_first,
                "public_no_key": provider.public_no_key,
                "configured": provider.configured(),
                "missing_env": list(provider.missing_env()),
                "readiness": provider.readiness().value,
                "data_supported": provider.data_supported,
                "demo_execution_supported": provider.demo_execution_supported,
                "live_execution_certified": provider.live_execution_certified,
                "notes": list(provider.notes),
            }
        )
    return tuple(rows)
