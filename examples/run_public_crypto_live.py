from __future__ import annotations

import argparse
import asyncio

from aura.data.public_crypto_feeds import (
    BybitPublicTickerFeed,
    CoinbasePublicTickerFeed,
    OkxPublicTickerFeed,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream public/no-key crypto market data into AURA normalization."
    )
    parser.add_argument("provider", choices=("coinbase", "bybit", "okx"))
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--market", default="spot", help="Bybit: spot/linear/inverse/option")
    parser.add_argument("--max-quotes", type=int, default=0)
    return parser.parse_args()


async def main() -> None:
    args = _args()
    if args.provider == "coinbase":
        feed = CoinbasePublicTickerFeed(args.symbols)
    elif args.provider == "bybit":
        feed = BybitPublicTickerFeed(args.symbols, market=args.market)
    else:
        feed = OkxPublicTickerFeed(args.symbols)

    count = 0
    async for quote in feed.stream():
        print(quote.model_dump_json())
        count += 1
        if args.max_quotes and count >= args.max_quotes:
            feed.stop()
            break


if __name__ == "__main__":
    asyncio.run(main())
