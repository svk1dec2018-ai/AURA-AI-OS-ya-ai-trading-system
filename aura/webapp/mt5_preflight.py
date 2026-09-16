from __future__ import annotations

from typing import Any

from aura.data.mt5_demo import OfficialMT5Gateway


def mt5_demo_preflight(*, max_symbols: int = 200) -> dict[str, Any]:
    """Read-only validation of the currently logged-in local MT5 DEMO session.

    The check intentionally accepts no login/password.  It verifies that the
    official MetaTrader5 bridge is importable, the terminal is connected, the
    active account passes AURA's DEMO guard and a tradable broker universe can be
    discovered.  No order_check/order_send calls are made here.
    """

    if not 1 <= max_symbols <= 5000:
        raise ValueError("max_symbols must be between 1 and 5000")
    gateway = OfficialMT5Gateway()
    try:
        account = gateway.connect_current_demo_session()
        instruments = tuple(item for item in gateway.discover_universe() if item.tradable)
        symbols = [
            {
                "symbol": item.venue_symbol,
                "asset_class": item.asset_class.value,
                "currency": item.currency,
                "tick_size": str(item.tick_size),
                "min_quantity": str(item.min_quantity),
                "quantity_step": str(item.quantity_step),
                "max_quantity": str(item.max_quantity) if item.max_quantity is not None else None,
            }
            for item in instruments[:max_symbols]
        ]
        return {
            "ok": True,
            "demo_verified": True,
            "connected": True,
            "account": {
                "login_last4": str(account.login)[-4:],
                "server": account.server,
                "currency": account.currency,
                "balance": str(account.balance),
                "equity": str(account.equity),
                "margin": str(account.margin),
                "margin_free": str(account.margin_free),
            },
            "tradable_symbol_count": len(instruments),
            "symbols": symbols,
            "order_submission_attempted": False,
            "real_money_enabled": False,
        }
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {
            "ok": False,
            "demo_verified": False,
            "connected": False,
            "error": str(exc),
            "symbols": [],
            "tradable_symbol_count": 0,
            "order_submission_attempted": False,
            "real_money_enabled": False,
        }
    finally:
        gateway.shutdown()
