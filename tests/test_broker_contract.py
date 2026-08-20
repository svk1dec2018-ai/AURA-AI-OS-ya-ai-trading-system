from __future__ import annotations

import pytest

from aura.execution.angel_one import AngelOneReadOnlyBroker
from aura.execution.broker import (
    BrokerCapabilities,
    BrokerExecutionMode,
    broker_adapter_conformance,
)
from aura.execution.dhan_sandbox import DhanSandboxBroker
from aura.execution.mt5_demo_broker import MT5DemoBroker
from aura.execution.paper import PaperBroker


@pytest.mark.parametrize(
    "adapter",
    (PaperBroker, AngelOneReadOnlyBroker, MT5DemoBroker, DhanSandboxBroker),
)
def test_declared_broker_adapters_conform_to_common_contract(adapter) -> None:
    assert broker_adapter_conformance(adapter) == ()
    assert adapter.capabilities.live_money_enabled is False


def test_read_only_capabilities_cannot_advertise_order_mutation() -> None:
    with pytest.raises(ValueError, match="read-only"):
        BrokerCapabilities(
            mode=BrokerExecutionMode.READ_ONLY,
            supports_order_submission=True,
            supports_order_cancellation=False,
            supports_fill_stream=True,
            supports_reconciliation=True,
        )


def test_non_live_mode_cannot_enable_live_money() -> None:
    with pytest.raises(ValueError, match="CONTROLLED_LIVE"):
        BrokerCapabilities(
            mode=BrokerExecutionMode.DEMO,
            supports_order_submission=True,
            supports_order_cancellation=True,
            supports_fill_stream=True,
            supports_reconciliation=True,
            live_money_enabled=True,
        )
