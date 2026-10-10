"""Read-only inventory of the connected DEMO broker's entire symbol universe."""

import argparse
import json
import os
from pathlib import Path

from aura.data.mt5_demo import OfficialMT5Gateway, load_mt5_demo_credentials_from_env
from aura.data.mt5_session import MT5_SESSION_LOCK
from aura.markets.mt5_profile import market_inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-symbols", type=int, default=0, help="0 = all broker symbols")
    parser.add_argument("--output", type=Path, default=Path("runtime/mt5_market_inventory.json"))
    args = parser.parse_args()
    gateway = OfficialMT5Gateway()
    try:
        with MT5_SESSION_LOCK:
            if os.environ.get("AURA_MT5_DEMO_LOGIN", "").strip():
                gateway.connect_demo(load_mt5_demo_credentials_from_env())
            else:
                gateway.connect_current_demo_session(
                    os.environ.get("AURA_MT5_TERMINAL_PATH", "").strip() or None
                )
            report = {
                "ok": True,
                **market_inventory(gateway.discover_universe(), max_symbols=args.max_symbols),
            }
    except (RuntimeError, ValueError, TypeError, OSError) as exc:
        report = {"ok": False, "error": str(exc), "order_submission_attempted": False}
    finally:
        gateway.shutdown()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
