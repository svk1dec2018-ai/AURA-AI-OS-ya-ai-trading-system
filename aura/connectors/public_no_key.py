from __future__ import annotations

from aura.connectors.catalog import (
    Capability,
    ConnectorCatalog,
    ConnectorDescriptor,
    ConnectorKind,
    ConnectorMaturity,
    CostTier,
)


PUBLIC_NO_KEY_CONNECTOR_CATALOG = ConnectorCatalog(
    (
        ConnectorDescriptor(
            connector_id="coinbase_public",
            display_name="Coinbase Advanced Trade Public Market Data",
            kind=ConnectorKind.MARKET_DATA,
            regions=("GLOBAL",),
            markets=("CRYPTO",),
            capabilities=frozenset(
                {
                    Capability.LIVE_QUOTES,
                    Capability.WEBSOCKET,
                }
            ),
            cost_tier=CostTier.FREE,
            maturity=ConnectorMaturity.ADAPTER_IMPLEMENTED,
            notes=(
                "AURA implements public ticker and market-trade WebSocket ingestion; no order authority.",
            ),
        ),
        ConnectorDescriptor(
            connector_id="bybit_public",
            display_name="Bybit V5 Public Market Data",
            kind=ConnectorKind.MARKET_DATA,
            regions=("GLOBAL",),
            markets=("CRYPTO",),
            capabilities=frozenset(
                {
                    Capability.LIVE_QUOTES,
                    Capability.WEBSOCKET,
                }
            ),
            cost_tier=CostTier.FREE,
            maturity=ConnectorMaturity.ADAPTER_IMPLEMENTED,
            notes=(
                "AURA implements public ticker and public-trade WebSocket ingestion; no order authority.",
            ),
        ),
        ConnectorDescriptor(
            connector_id="okx_public",
            display_name="OKX V5 Public Market Data",
            kind=ConnectorKind.MARKET_DATA,
            regions=("GLOBAL",),
            markets=("CRYPTO",),
            capabilities=frozenset(
                {
                    Capability.LIVE_QUOTES,
                    Capability.WEBSOCKET,
                }
            ),
            cost_tier=CostTier.FREE,
            maturity=ConnectorMaturity.ADAPTER_IMPLEMENTED,
            notes=(
                "AURA currently implements the public ticker path for redundant quote checks; no order authority.",
            ),
        ),
    )
)
