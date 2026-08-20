from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from aura.domain.models import Fill, OrderRequest


class BrokerExecutionMode(str, Enum):
    PAPER = "PAPER"
    DEMO = "DEMO"
    SANDBOX = "SANDBOX"
    READ_ONLY = "READ_ONLY"
    CONTROLLED_LIVE = "CONTROLLED_LIVE"


@dataclass(slots=True, frozen=True)
class BrokerCapabilities:
    """Truthful adapter permissions; capability flags never grant authority."""

    mode: BrokerExecutionMode
    supports_order_submission: bool
    supports_order_cancellation: bool
    supports_fill_stream: bool
    supports_reconciliation: bool
    live_money_enabled: bool = False

    def __post_init__(self) -> None:
        if self.live_money_enabled and self.mode != BrokerExecutionMode.CONTROLLED_LIVE:
            raise ValueError("live money requires CONTROLLED_LIVE mode")
        if self.mode == BrokerExecutionMode.READ_ONLY and (
            self.supports_order_submission or self.supports_order_cancellation
        ):
            raise ValueError("read-only adapters cannot advertise order mutation")


class BrokerAdapter(ABC):
    """Broker-agnostic execution contract.

    Live broker implementations must translate their native order/fill schema
    into AURA domain models. Strategy code must never call broker SDKs directly.
    """

    name: str
    capabilities: BrokerCapabilities

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def submit_order(self, order: OrderRequest) -> str:
        """Submit an approved AURA order and return broker order id."""
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def fills(self) -> AsyncIterator[Fill]:
        """Yield normalized fills. Implementations must deduplicate/reconcile."""
        raise NotImplementedError


def broker_adapter_conformance(adapter_type: type[Any]) -> tuple[str, ...]:
    """Return deterministic contract violations without connecting to a broker."""

    errors: list[str] = []
    if not inspect.isclass(adapter_type) or not issubclass(adapter_type, BrokerAdapter):
        return ("adapter must subclass BrokerAdapter",)
    if inspect.isabstract(adapter_type):
        errors.append("adapter has unimplemented BrokerAdapter methods")
    name = getattr(adapter_type, "name", "")
    if not isinstance(name, str) or not name.strip():
        errors.append("adapter name is required")
    capabilities = getattr(adapter_type, "capabilities", None)
    if not isinstance(capabilities, BrokerCapabilities):
        errors.append("adapter must declare BrokerCapabilities")
        return tuple(errors)
    if capabilities.supports_reconciliation:
        for method_name in ("open_order_snapshots", "position_snapshots"):
            if not callable(getattr(adapter_type, method_name, None)):
                errors.append(f"reconciliation capability requires {method_name}()")
    if capabilities.supports_fill_stream and not callable(getattr(adapter_type, "fills", None)):
        errors.append("fill-stream capability requires fills()")
    return tuple(errors)
