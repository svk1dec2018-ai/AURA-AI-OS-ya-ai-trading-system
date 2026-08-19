from aura.connectors.catalog import (
    DEFAULT_CONNECTOR_CATALOG,
    Capability,
    ConnectorMaturity,
    CostTier,
)


def test_connector_catalog_tracks_truthful_maturity_and_cost() -> None:
    shoonya = DEFAULT_CONNECTOR_CATALOG.get("shoonya")
    assert shoonya.maturity == ConnectorMaturity.ADAPTER_IMPLEMENTED
    assert shoonya.cost_tier == CostTier.FREE_ACCOUNT_REQUIRED
    assert Capability.WEBSOCKET in shoonya.capabilities

    dhan = DEFAULT_CONNECTOR_CATALOG.get("dhan")
    assert dhan.cost_tier == CostTier.PAID_DATA
    assert Capability.OPTION_CHAIN in dhan.capabilities


def test_free_live_data_filter_excludes_paid_data_connectors() -> None:
    connectors = DEFAULT_CONNECTOR_CATALOG.matching(
        capability=Capability.LIVE_QUOTES,
        free_only=True,
    )
    ids = {item.connector_id for item in connectors}
    assert "shoonya" in ids
    assert "upstox" in ids
    assert "dhan" not in ids
    assert "zerodha_kite" not in ids


def test_missing_environment_is_explicit_not_validation_claim() -> None:
    shoonya = DEFAULT_CONNECTOR_CATALOG.get("shoonya")
    missing = shoonya.missing_environment({})
    assert missing == (
        "AURA_SHOONYA_USER_ID",
        "AURA_SHOONYA_ACCOUNT_ID",
        "AURA_SHOONYA_SESSION_TOKEN",
    )

    angel_one = DEFAULT_CONNECTOR_CATALOG.get("angel_one_smartapi")
    assert angel_one.maturity == ConnectorMaturity.ADAPTER_IMPLEMENTED
    assert angel_one.missing_environment({}) == (
        "AURA_ANGEL_ONE_API_KEY",
        "AURA_ANGEL_ONE_CLIENT_CODE",
        "AURA_ANGEL_ONE_JWT_TOKEN",
        "AURA_ANGEL_ONE_REFRESH_TOKEN",
    )
