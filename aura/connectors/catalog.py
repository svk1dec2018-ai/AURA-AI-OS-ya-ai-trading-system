from __future__ import annotations

import os
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConnectorKind(str, Enum):
    BROKER = "broker"
    MARKET_DATA = "market_data"
    NEWS = "news"
    MACRO = "macro"
    FUNDAMENTALS = "fundamentals"


class Capability(str, Enum):
    LIVE_QUOTES = "live_quotes"
    WEBSOCKET = "websocket"
    DEPTH = "depth"
    HISTORICAL = "historical"
    ORDERS = "orders"
    ORDER_UPDATES = "order_updates"
    POSITIONS = "positions"
    OPTIONS = "options"
    OPTION_CHAIN = "option_chain"
    GREEKS = "greeks"
    OPEN_INTEREST = "open_interest"
    PAPER = "paper"
    DEMO = "demo"
    NEWS = "news"
    SENTIMENT = "sentiment"
    ECONOMIC_RELEASES = "economic_releases"
    FILINGS = "filings"
    FUNDAMENTALS = "fundamentals"


class CostTier(str, Enum):
    FREE = "free"
    FREE_ACCOUNT_REQUIRED = "free_account_required"
    FREE_KEY_REQUIRED = "free_key_required"
    PAID_DATA = "paid_data"
    PAID = "paid"
    UNKNOWN = "unknown"


class ConnectorMaturity(str, Enum):
    RESEARCHED = "researched"
    ADAPTER_IMPLEMENTED = "adapter_implemented"
    CREDENTIAL_VALIDATED = "credential_validated"
    PAPER_VALIDATED = "paper_validated"
    LIVE_ELIGIBLE = "live_eligible"


class ConnectorDescriptor(BaseModel):
    """Truthful capability/readiness record; it is not an execution permission."""

    model_config = ConfigDict(frozen=True)

    connector_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    kind: ConnectorKind
    regions: tuple[str, ...] = ()
    markets: tuple[str, ...] = ()
    capabilities: frozenset[Capability] = frozenset()
    cost_tier: CostTier = CostTier.UNKNOWN
    maturity: ConnectorMaturity = ConnectorMaturity.RESEARCHED
    required_env: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_descriptor(self) -> ConnectorDescriptor:
        if len(self.required_env) != len(set(self.required_env)):
            raise ValueError(f"duplicate required_env for {self.connector_id}")
        return self

    def missing_environment(self, environ: dict[str, str] | None = None) -> tuple[str, ...]:
        values = environ if environ is not None else os.environ
        return tuple(name for name in self.required_env if not values.get(name, "").strip())

    @property
    def has_execution(self) -> bool:
        return Capability.ORDERS in self.capabilities

    @property
    def has_live_data(self) -> bool:
        return Capability.LIVE_QUOTES in self.capabilities


class ConnectorCatalog:
    def __init__(self, descriptors: tuple[ConnectorDescriptor, ...]) -> None:
        ids = [item.connector_id for item in descriptors]
        if len(ids) != len(set(ids)):
            raise ValueError("connector ids must be unique")
        self._descriptors = {item.connector_id: item for item in descriptors}

    def all(self) -> tuple[ConnectorDescriptor, ...]:
        return tuple(self._descriptors[key] for key in sorted(self._descriptors))

    def get(self, connector_id: str) -> ConnectorDescriptor:
        return self._descriptors[connector_id]

    def matching(
        self,
        *,
        capability: Capability | None = None,
        kind: ConnectorKind | None = None,
        free_only: bool = False,
    ) -> tuple[ConnectorDescriptor, ...]:
        free_tiers = {
            CostTier.FREE,
            CostTier.FREE_ACCOUNT_REQUIRED,
            CostTier.FREE_KEY_REQUIRED,
        }
        result = []
        for descriptor in self._descriptors.values():
            if capability is not None and capability not in descriptor.capabilities:
                continue
            if kind is not None and descriptor.kind != kind:
                continue
            if free_only and descriptor.cost_tier not in free_tiers:
                continue
            result.append(descriptor)
        return tuple(sorted(result, key=lambda item: item.connector_id))

    def missing_environment(self) -> dict[str, tuple[str, ...]]:
        return {
            item.connector_id: missing
            for item in self.all()
            if (missing := item.missing_environment())
        }


_BROKER = ConnectorKind.BROKER


DEFAULT_CONNECTOR_CATALOG = ConnectorCatalog(
    (
        ConnectorDescriptor(
            connector_id="exness_mt5",
            display_name="Exness / MetaTrader 5",
            kind=_BROKER,
            regions=("GLOBAL",),
            markets=("FOREX", "METALS", "ENERGY", "INDICES_CFD", "STOCK_CFD", "CRYPTO_CFD"),
            capabilities=frozenset(
                {
                    Capability.LIVE_QUOTES,
                    Capability.HISTORICAL,
                    Capability.ORDERS,
                    Capability.ORDER_UPDATES,
                    Capability.POSITIONS,
                    Capability.DEMO,
                }
            ),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.ADAPTER_IMPLEMENTED,
            required_env=("AURA_MT5_DEMO_LOGIN", "AURA_MT5_DEMO_PASSWORD", "AURA_MT5_DEMO_SERVER"),
            notes=("Self-evolving AURA runner remains internal-paper by default.",),
        ),
        ConnectorDescriptor(
            connector_id="dhan",
            display_name="DhanHQ",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "BFO", "MCX"),
            capabilities=frozenset(
                {
                    Capability.LIVE_QUOTES,
                    Capability.WEBSOCKET,
                    Capability.DEPTH,
                    Capability.HISTORICAL,
                    Capability.ORDERS,
                    Capability.ORDER_UPDATES,
                    Capability.POSITIONS,
                    Capability.OPTIONS,
                    Capability.OPTION_CHAIN,
                    Capability.GREEKS,
                    Capability.OPEN_INTEREST,
                }
            ),
            cost_tier=CostTier.PAID_DATA,
            maturity=ConnectorMaturity.ADAPTER_IMPLEMENTED,
            required_env=("AURA_DHAN_CLIENT_ID", "AURA_DHAN_ACCESS_TOKEN"),
            notes=("Official Data API subscription is separate from trading API access.",),
        ),
        ConnectorDescriptor(
            connector_id="shoonya",
            display_name="Shoonya by Finvasia",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "CDS", "MCX"),
            capabilities=frozenset(
                {
                    Capability.LIVE_QUOTES,
                    Capability.WEBSOCKET,
                    Capability.DEPTH,
                    Capability.HISTORICAL,
                    Capability.ORDERS,
                    Capability.ORDER_UPDATES,
                    Capability.POSITIONS,
                    Capability.OPTIONS,
                    Capability.OPTION_CHAIN,
                    Capability.OPEN_INTEREST,
                }
            ),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.ADAPTER_IMPLEMENTED,
            required_env=("AURA_SHOONYA_USER_ID", "AURA_SHOONYA_ACCOUNT_ID", "AURA_SHOONYA_SESSION_TOKEN"),
            notes=("AURA adapter is market-data first; execution stays disabled until broker-specific reconciliation is validated.",),
        ),
        ConnectorDescriptor(
            connector_id="upstox",
            display_name="Upstox API",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "MCX"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.OPTIONS}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.RESEARCHED,
        ),
        ConnectorDescriptor(
            connector_id="angel_one_smartapi",
            display_name="Angel One SmartAPI",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "BFO", "MCX"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.DEPTH, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.OPEN_INTEREST}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.RESEARCHED,
            notes=("Order APIs are subject to current static-IP/regulatory requirements.",),
        ),
        ConnectorDescriptor(
            connector_id="fyers",
            display_name="FYERS Trading API",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "MCX"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.RESEARCHED,
            notes=("Execution eligibility must follow FYERS current retail-algo/static-IP rules.",),
        ),
        ConnectorDescriptor(
            connector_id="flattrade",
            display_name="Flattrade Pi",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "CDS", "MCX"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.DEPTH, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.OPTIONS, Capability.OPTION_CHAIN, Capability.OPEN_INTEREST}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.RESEARCHED,
            notes=("Pi v2 execution use is subject to current exchange approval/static-IP rules.",),
        ),
        ConnectorDescriptor(
            connector_id="kotak_neo",
            display_name="Kotak Neo Trade API",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "BFO", "CDS", "MCX"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS}),
            cost_tier=CostTier.UNKNOWN,
            maturity=ConnectorMaturity.RESEARCHED,
        ),
        ConnectorDescriptor(
            connector_id="alice_blue",
            display_name="Alice Blue ANT API",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "CDS", "MCX"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS}),
            cost_tier=CostTier.UNKNOWN,
            maturity=ConnectorMaturity.RESEARCHED,
        ),
        ConnectorDescriptor(
            connector_id="fivepaisa",
            display_name="5paisa Developer API",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "MCX"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.DEPTH, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.OPEN_INTEREST}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.RESEARCHED,
        ),
        ConnectorDescriptor(
            connector_id="icici_breeze",
            display_name="ICICI Direct Breeze",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "NFO"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.OPTIONS}),
            cost_tier=CostTier.UNKNOWN,
            maturity=ConnectorMaturity.RESEARCHED,
        ),
        ConnectorDescriptor(
            connector_id="zerodha_kite",
            display_name="Zerodha Kite Connect",
            kind=_BROKER,
            regions=("INDIA",),
            markets=("NSE", "BSE", "NFO", "MCX"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.DEPTH, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.OPEN_INTEREST}),
            cost_tier=CostTier.PAID_DATA,
            maturity=ConnectorMaturity.RESEARCHED,
            notes=("Personal execution/account APIs have a free tier; real-time and historical data are on the Connect data tier.",),
        ),
        ConnectorDescriptor(
            connector_id="ctrader_open_api",
            display_name="cTrader Open API",
            kind=_BROKER,
            regions=("GLOBAL",),
            markets=("FOREX", "CFD"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.DEMO}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.RESEARCHED,
        ),
        ConnectorDescriptor(
            connector_id="oanda_v20",
            display_name="OANDA v20 REST API",
            kind=_BROKER,
            regions=("GLOBAL",),
            markets=("FOREX", "CFD"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.DEMO}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.RESEARCHED,
        ),
        ConnectorDescriptor(
            connector_id="alpaca",
            display_name="Alpaca Trading / Market Data API",
            kind=_BROKER,
            regions=("US", "GLOBAL_PAPER"),
            markets=("US_EQUITIES", "US_OPTIONS", "CRYPTO"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.OPTIONS, Capability.PAPER}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.RESEARCHED,
            notes=("Free Basic market data has coverage limits; paper-only accounts are globally available.",),
        ),
        ConnectorDescriptor(
            connector_id="ibkr",
            display_name="Interactive Brokers TWS API",
            kind=_BROKER,
            regions=("GLOBAL",),
            markets=("EQUITIES", "OPTIONS", "FUTURES", "FOREX", "BONDS"),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.OPTIONS, Capability.PAPER}),
            cost_tier=CostTier.UNKNOWN,
            maturity=ConnectorMaturity.RESEARCHED,
        ),
        ConnectorDescriptor(
            connector_id="binance",
            display_name="Binance",
            kind=_BROKER,
            regions=("GLOBAL",),
            markets=("CRYPTO",),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.DEPTH, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS, Capability.DEMO}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.ADAPTER_IMPLEMENTED,
        ),
        ConnectorDescriptor(
            connector_id="kraken",
            display_name="Kraken",
            kind=_BROKER,
            regions=("GLOBAL",),
            markets=("CRYPTO",),
            capabilities=frozenset({Capability.LIVE_QUOTES, Capability.WEBSOCKET, Capability.DEPTH, Capability.HISTORICAL, Capability.ORDERS, Capability.ORDER_UPDATES, Capability.POSITIONS}),
            cost_tier=CostTier.FREE_ACCOUNT_REQUIRED,
            maturity=ConnectorMaturity.ADAPTER_IMPLEMENTED,
        ),
    )
)
