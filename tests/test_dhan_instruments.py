from decimal import Decimal

from aura.data.dhan_instruments import DhanExchangeSegment, DhanInstrumentMaster
from aura.markets.universe import AssetClass, OptionType, VenueFamily


CSV = """SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,SEM_SERIES,SM_SYMBOL_NAME
NSE_EQ,1333,EQUITY,HDFCBANK,1,HDFCBANK,,, ,0.05,EQ,HDFCBANK
NSE_FNO,50001,FUTIDX,NIFTY-AUG2026-FUT,75,NIFTY AUG FUT,2026-08-27,0,,0.05,,NIFTY
NSE_FNO,50002,OPTIDX,NIFTY-AUG2026-25000-CE,75,NIFTY AUG 25000 CE,2026-08-27,25000,CE,0.05,,NIFTY
BSE_FNO,60002,OPTIDX,SENSEX-AUG2026-82000-PE,20,SENSEX AUG 82000 PE,2026-08-27,82000,PE,0.05,,SENSEX
MCX_COMM,70001,FUTCOM,GOLD-OCT2026-FUT,1,GOLD OCT FUT,2026-10-05,0,,1.0,,GOLD
"""


def test_dhan_master_builds_cash_future_option_and_mcx_contracts() -> None:
    master = DhanInstrumentMaster.from_csv_text(CSV)
    instruments = master.to_canonical_universe()
    assert len(instruments) == 5
    assert all(item.venue_family == VenueFamily.DHAN_INDIA for item in instruments)
    by_security = {item.venue_symbol: item for item in instruments}

    assert by_security["1333"].asset_class == AssetClass.CASH_EQUITY
    assert by_security["1333"].min_quantity == Decimal(1)

    nifty_future = by_security["50001"]
    assert nifty_future.asset_class == AssetClass.FUTURE
    assert nifty_future.underlying == "NIFTY"
    assert nifty_future.lot_size == Decimal(75)
    assert nifty_future.contract_size == Decimal(1)

    nifty_call = by_security["50002"]
    assert nifty_call.asset_class == AssetClass.OPTION
    assert nifty_call.option_type == OptionType.CALL
    assert nifty_call.strike == Decimal(25000)
    assert nifty_call.min_quantity == Decimal(75)

    sensex_put = by_security["60002"]
    assert sensex_put.option_type == OptionType.PUT
    assert sensex_put.lot_size == Decimal(20)

    mcx = by_security["70001"]
    assert mcx.exchange == "MCX"
    assert mcx.asset_class == AssetClass.FUTURE
    assert mcx.underlying == "GOLD"


def test_dhan_master_can_limit_segments() -> None:
    master = DhanInstrumentMaster.from_csv_text(CSV)
    instruments = master.to_canonical_universe(
        include_segments=frozenset({DhanExchangeSegment.NSE_EQ})
    )
    assert len(instruments) == 1
    assert instruments[0].exchange == "NSE"
