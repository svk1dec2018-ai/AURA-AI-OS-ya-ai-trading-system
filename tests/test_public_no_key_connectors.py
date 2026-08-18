from aura.connectors.catalog import Capability, ConnectorKind, ConnectorMaturity, CostTier
from aura.connectors.public_no_key import PUBLIC_NO_KEY_CONNECTOR_CATALOG


def test_public_no_key_connectors_are_data_only_and_free() -> None:
    descriptors = PUBLIC_NO_KEY_CONNECTOR_CATALOG.all()
    assert {item.connector_id for item in descriptors} == {
        "bybit_public",
        "coinbase_public",
        "okx_public",
    }
    for item in descriptors:
        assert item.kind == ConnectorKind.MARKET_DATA
        assert item.cost_tier == CostTier.FREE
        assert item.maturity == ConnectorMaturity.ADAPTER_IMPLEMENTED
        assert Capability.LIVE_QUOTES in item.capabilities
        assert Capability.WEBSOCKET in item.capabilities
        assert Capability.ORDERS not in item.capabilities
        assert item.required_env == ()
