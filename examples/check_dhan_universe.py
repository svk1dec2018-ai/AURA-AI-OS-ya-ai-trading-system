from __future__ import annotations

import argparse
from collections import Counter

from aura.data.dhan_instruments import DhanInstrumentMasterDownloader
from aura.data.dhan_universe_planner import DhanUniversePlanner, DhanUniversePolicy


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Dhan detailed master and verify AURA Indian market universe."
    )
    parser.add_argument("--stream-cap", type=int, default=5000)
    parser.add_argument("--cash-cap", type=int, default=3500)
    parser.add_argument("--futures-cap", type=int, default=1200)
    return parser.parse_args()


def main() -> None:
    args = _args()
    master = DhanInstrumentMasterDownloader().download()
    universe = master.to_canonical_universe()
    plan = DhanUniversePlanner(
        DhanUniversePolicy(
            max_stream_instruments=args.stream_cap,
            max_primary_cash_symbols=args.cash_cap,
            max_primary_futures=args.futures_cap,
        )
    ).primary_plan(universe)
    by_asset = Counter(item.asset_class.value for item in universe)
    by_segment = Counter(item.segment or "unknown" for item in universe)
    print(f"Canonical Indian instruments: {len(universe)}")
    print(f"Primary live-stream plan: {len(plan.streamed)}")
    print(f"Indexed options: {len(plan.indexed_options)}")
    print(f"Deferred cash/futures: {len(plan.deferred)}")
    print("Assets:", dict(sorted(by_asset.items())))
    print("Segments:", dict(sorted(by_segment.items())))
    print(
        "Options remain fully indexed and are activated around an underlying/expiry "
        "opportunity instead of wasting the live stream cap on far-OTM strikes."
    )


if __name__ == "__main__":
    main()
