"""Owner market priorities; actual membership always comes from MT5 discovery."""

from __future__ import annotations

from collections import Counter

# Aliases are selection hints, never synthetic contracts or guaranteed availability.
MT5_MARKET_PRIORITIES = (
    ("gold", ("XAUUSD", "GOLD")),
    ("wti_oil", ("USOIL", "XTIUSD", "WTI")),
    ("bitcoin", ("BTCUSD", "BITCOIN", "BTC")),
    ("eurusd", ("EURUSD",)),
    ("gbpusd", ("GBPUSD",)),
    ("usdjpy", ("USDJPY",)),
    ("audusd", ("AUDUSD",)),
    ("usdcad", ("USDCAD",)),
    ("usdchf", ("USDCHF",)),
    ("nzdusd", ("NZDUSD",)),
    ("silver", ("XAGUSD", "SILVER")),
    ("ethereum", ("ETHUSD", "ETHEREUM", "ETH")),
    ("brent_oil", ("UKOIL", "XBRUSD", "BRENT")),
    ("natural_gas", ("XNGUSD", "NATGAS", "NGAS")),
    ("us30", ("US30", "DJ30", "DJI")),
    ("nasdaq", ("USTEC", "NAS100", "US100")),
    ("sp500", ("US500", "SPX500", "SP500")),
    ("germany", ("DE40", "GER40", "DE30", "GER30")),
    ("uk100", ("UK100", "FTSE100")),
    ("japan", ("JP225", "JPN225")),
)


def market_priority(symbol: str) -> tuple[int, int]:
    upper = symbol.upper()
    for index, (_, aliases) in enumerate(MT5_MARKET_PRIORITIES):
        for alias in aliases:
            if upper == alias or upper.startswith(alias):
                return index, len(upper) - len(alias)
    return len(MT5_MARKET_PRIORITIES), len(upper)


def market_inventory(instruments, *, max_symbols: int = 0) -> dict:
    """Report eligible metadata coverage, not quote/execution readiness."""
    if not 0 <= max_symbols <= 1000:
        raise ValueError("scan limit must be 0 (all) or 1..1000")
    all_items = tuple(instruments)
    eligible = sorted(
        (item for item in all_items if item.tradable and item.market_data_enabled),
        key=lambda item: (*market_priority(item.venue_symbol), item.venue_symbol),
    )
    selected = eligible[:max_symbols] if max_symbols else eligible
    selected_names = {item.venue_symbol for item in selected}
    by_segment = Counter(item.asset_class.value for item in eligible)
    targets = []
    for index, (name, aliases) in enumerate(MT5_MARKET_PRIORITIES):
        matches = [
            item.venue_symbol for item in eligible if market_priority(item.venue_symbol)[0] == index
        ]
        targets.append(
            {
                "market": name,
                "aliases": list(aliases),
                "broker_symbols": matches,
                "selected_symbols": [s for s in matches if s in selected_names],
                "state": "DISCOVERED_METADATA" if matches else "NOT_OFFERED_OR_NOT_ENTRY_ELIGIBLE",
            }
        )
    return {
        "scope": "BROKER_DISCOVERED_MT5_DEMO",
        "scan_limit": max_symbols,
        "all_symbols_selected": len(selected) == len(eligible),
        "discovered": len(all_items),
        "entry_eligible": len(eligible),
        "selected": len(selected),
        "excluded_or_disabled": len(all_items) - len(eligible),
        "segments": dict(sorted(by_segment.items())),
        "priority_markets": targets,
        "symbols": [
            {
                "symbol": item.venue_symbol,
                "segment": item.asset_class.value,
                "selected": item.venue_symbol in selected_names,
            }
            for item in eligible
        ],
        "execution_verified": False,
        "order_submission_attempted": False,
        "note": "Metadata eligibility does not prove open session, fresh quotes, affordable size or broker order acceptance.",
    }
