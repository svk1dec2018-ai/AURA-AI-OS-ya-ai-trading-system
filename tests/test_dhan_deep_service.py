import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.data.candle_aggregation import CanonicalTradeTick
from aura.data.dhan_deep_service import DhanDeepMetadataService
from aura.data.dhan_live_ticker import DhanLiveCredentials
from aura.markets.universe import AssetClass, CanonicalInstrument, VenueFamily


def _instrument(symbol: str) -> CanonicalInstrument:
    return CanonicalInstrument(
        instrument_id=f"dhan:{symbol}",
        canonical_symbol=symbol,
        venue_family=VenueFamily.DHAN_INDIA,
        venue_symbol=symbol,
        asset_class=AssetClass.CASH_EQUITY,
        exchange="NSE",
        segment="NSE_EQ",
        currency="INR",
        tick_size=Decimal("0.05"),
        min_quantity=Decimal(1),
        quantity_step=Decimal(1),
    )


class FakeFullSource:
    def __init__(self, subscriptions) -> None:
        self.subscriptions = subscriptions
        self._stopped = False
        self._metadata = {}

    def stop(self) -> None:
        self._stopped = True

    def metadata_for(self, symbol: str) -> dict:
        return dict(self._metadata.get(symbol, {}))

    async def ticks(self):
        now = datetime.now(UTC)
        for subscription in self.subscriptions:
            if self._stopped:
                break
            self._metadata[subscription.symbol] = {
                "execution_quality": {
                    "source_id": f"fake:{subscription.symbol}",
                    "observed_at": now.isoformat(),
                    "spread_bps": 2.0,
                    "estimated_slippage_bps": 1.0,
                    "top_of_book_notional": 100000.0,
                    "trust_score": 1.0,
                }
            }
            yield CanonicalTradeTick(
                symbol=subscription.symbol,
                venue="DHAN_LIVE_FULL",
                price=Decimal(100),
                quantity=Decimal(1),
                timestamp=now,
            )
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_deep_service_rotates_and_returns_fresh_metadata() -> None:
    service = DhanDeepMetadataService(
        DhanLiveCredentials("client", "token"),
        (_instrument("AAA"), _instrument("BBB")),
        source_factory=lambda subscriptions: FakeFullSource(subscriptions),
    )
    assert await service.update_symbols(("AAA",))
    await asyncio.sleep(0.01)
    now = datetime.now(UTC)
    metadata = service.metadata_for("AAA", decision_time=now)
    assert metadata["execution_quality"]["spread_bps"] == 2.0
    assert not await service.update_symbols(("AAA",))
    assert await service.update_symbols(("BBB",))
    assert service.active_symbols == ("BBB",)
    await service.stop()
    assert service.active_symbols == ()


def test_deep_service_rejects_stale_metadata() -> None:
    service = DhanDeepMetadataService(
        DhanLiveCredentials("client", "token"),
        (_instrument("AAA"),),
        source_factory=lambda subscriptions: FakeFullSource(subscriptions),
    )
    observed = datetime(2026, 8, 18, 3, 45, tzinfo=UTC)
    service._metadata["AAA"] = {
        "execution_quality": {
            "source_id": "fake:AAA",
            "observed_at": observed.isoformat(),
        }
    }
    assert (
        service.metadata_for(
            "AAA",
            decision_time=observed + timedelta(seconds=21),
            max_age_seconds=20,
        )
        == {}
    )
