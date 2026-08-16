from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from aura.domain.models import Fill, OrderRequest


class BrokerAdapter(ABC):
    """Broker-agnostic execution contract.

    Live broker implementations must translate their native order/fill schema
    into AURA domain models. Strategy code must never call broker SDKs directly.
    """

    name: str

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
