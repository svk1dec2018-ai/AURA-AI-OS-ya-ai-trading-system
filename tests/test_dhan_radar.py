from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.domain.models import NormalizedCandle
from aura.markets.universe import AssetClass, CanonicalInstrument, VenueFamily
from aura.runtime.dhan_radar import DhanOpportunityRadar, DhanRadarPolicy


def _instrument(symbol: str, asset_class: AssetClass, *, tradable: bool = True):
    return CanonicalInstrument(
        instrument_id=f"dhan:{symbol}",
        canonical_symbol=symbol,
        venue_family=VenueFamily.DHAN_INDIA,
        venue_symbol=symbol,
        asset_class=asset_class,
        exchange="NSE",
        segment="IDX_I" if asset_class == AssetClass.INDEX else "NSE_EQ",
        currency="INR",
        tick_size=Decimal("0.05"),
        min_quantity=Decimal(1),
        quantity_step=Decimal(1),
        tradable=tradable,
        market_data_enabled=True,
    )


def _candle(symbol: str, close_time: datetime, open_price: str, close_price: str):
    open_value = Decimal(open_price)
    close_value = Decimal(close_price)
    return NormalizedCandle(
        symbol=symbol,
        venue="DHAN_LIVE",
        timeframe="1m",
        open_time=close_time - timedelta(minutes=1),
        close_time=close_time,
        open=open_value,
        high=max(open_value, close_value) + Decimal("0.2"),
        low=min(open_value, close_value) - Decimal("0.2"),
        close=close_value,
        volume=Decimal(0),
        closed=True,
    )


def test_radar_selects_strongest_tradable_and_keeps_index_context() -> None:
    instruments = (
        _instrument("NIFTY", AssetClass.INDEX, tradable=False),
        _instrument("AAA", AssetClass.CASH_EQUITY),
        _instrument("BBB", AssetClass.CASH_EQUITY),
    )
    radar = DhanOpportunityRadar(
        instruments,
        policy=DhanRadarPolicy(top_k_tradable=1, min_history_bars=3),
    )
    base = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
    for minute in range(3):
        radar.observe(
            (
                _candle("NIFTY", base + timedelta(minutes=minute), "25000", "25001"),
                _candle("AAA", base + timedelta(minutes=minute), "100", str(100 + minute)),
                _candle("BBB", base + timedelta(minutes=minute), "100", str(100 + 3 * minute)),
            )
        )
    selection = radar.last_selection
    assert selection.selected_tradable_symbols == ("BBB",)
    assert selection.context_index_symbols == ("NIFTY",)
    assert selection.ranked[0].symbol == "BBB"


def test_priority_symbol_is_never_dropped_from_deep_shortlist() -> None:
    instruments = (
        _instrument("AAA", AssetClass.CASH_EQUITY),
        _instrument("BBB", AssetClass.CASH_EQUITY),
    )
    radar = DhanOpportunityRadar(
        instruments,
        policy=DhanRadarPolicy(top_k_tradable=1, min_history_bars=3),
    )
    radar.set_priority_symbols({"AAA"})
    base = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
    for minute in range(3):
        radar.observe(
            (
                _candle("AAA", base + timedelta(minutes=minute), "100", "100.1"),
                _candle("BBB", base + timedelta(minutes=minute), "100", str(100 + 5 * minute)),
            )
        )
    assert radar.last_selection.selected_tradable_symbols == ("BBB", "AAA")
