from __future__ import annotations

import asyncio
import json

from aura.execution.angel_one import (
    AngelOneReadOnlyBroker,
    create_official_smartapi_client,
    load_angel_one_session_from_env,
)


async def main() -> None:
    credentials = load_angel_one_session_from_env()
    broker = AngelOneReadOnlyBroker(
        create_official_smartapi_client(credentials),
        credentials,
        routes={},
    )
    await broker.connect()
    try:
        orders = broker.open_order_snapshots()
        positions = broker.position_snapshots()
    finally:
        await broker.disconnect()
    print(
        json.dumps(
            {
                "connector": "angel_one_smartapi",
                "profile_verified": True,
                "execution_enabled": False,
                "open_orders": len(orders),
                "open_positions": len(positions),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
