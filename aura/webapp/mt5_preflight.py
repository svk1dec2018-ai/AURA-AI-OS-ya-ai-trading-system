from __future__ import annotations

from decimal import Decimal
from typing import Any

from aura.data.mt5_demo import OfficialMT5Gateway
from aura.domain.models import Side
from aura.execution.mt5_protected_demo import (
    ProtectedMT5DemoBroker,
    ProtectedMT5DemoConfig,
    _protected_prices,
)


def mt5_demo_preflight(*, max_symbols: int = 200, query: str = "") -> dict[str, Any]:
    """Read-only validation of the currently logged-in local MT5 DEMO session.

    The check intentionally accepts no login/password. It verifies that the
    official MetaTrader5 bridge is importable, the terminal is connected, the
    active account passes AURA's DEMO guard and a tradable broker universe can be
    discovered. No order_check/order_send calls are made here.
    """

    if not 1 <= max_symbols <= 5000:
        raise ValueError("max_symbols must be between 1 and 5000")
    if len(query) > 120:
        raise ValueError("symbol search must contain at most 120 characters")
    gateway = OfficialMT5Gateway()
    try:
        account = gateway.connect_current_demo_session()
        instruments = tuple(item for item in gateway.discover_universe() if item.tradable)
        raw_symbols = gateway.symbols_get()
        if raw_symbols is None:
            raise RuntimeError("MT5 symbol metadata unavailable")
        metadata = {str(_asdict(row).get("name")): _asdict(row) for row in raw_symbols}
        preferred = {symbol: index for index, symbol in enumerate(
            ("XAUUSD", "BTCUSD", "USOIL", "EURUSD", "GBPUSD", "XAGUSD")
        )}
        matching = sorted(
            (item for item in instruments if query.strip().casefold() in (
                f"{item.venue_symbol} {metadata.get(item.venue_symbol, {}).get('description', '')} "
                f"{metadata.get(item.venue_symbol, {}).get('path', '')}"
            ).casefold()),
            key=lambda item: (preferred.get(item.venue_symbol, len(preferred)), item.venue_symbol),
        )
        symbols = [
            {
                "symbol": item.venue_symbol,
                "description": str(metadata.get(item.venue_symbol, {}).get("description", "")),
                "broker_path": str(metadata.get(item.venue_symbol, {}).get("path", "")),
                "trade_mode": metadata.get(item.venue_symbol, {}).get("trade_mode"),
                "asset_class": item.asset_class.value,
                "currency": item.currency,
                "tick_size": str(item.tick_size),
                "min_quantity": str(item.min_quantity),
                "quantity_step": str(item.quantity_step),
                "max_quantity": str(item.max_quantity) if item.max_quantity is not None else None,
            }
            for item in matching[:max_symbols]
        ]
        return {
            "ok": True,
            "demo_verified": True,
            "connected": True,
            "account": _account_payload(account),
            "tradable_symbol_count": len(instruments),
            "matched_symbol_count": len(matching),
            "symbols_truncated": len(matching) > max_symbols,
            "query": query,
            "symbols": symbols,
            "order_check_attempted": False,
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
            "order_check_attempted": False,
            "order_submission_attempted": False,
            "real_money_enabled": False,
        }
    finally:
        gateway.shutdown()


def mt5_demo_execution_check(
    symbol: str,
    *,
    side: Side = Side.BUY,
    protection: ProtectedMT5DemoConfig | None = None,
) -> dict[str, Any]:
    """Validate one minimum-volume protected MT5 DEMO request without sending it.

    This is the final broker-side readiness probe before autonomous DEMO runtime
    start. It uses the same filling-mode and native SL/TP rules as the protected
    broker adapter, calls ``order_calc_margin`` and ``order_check``, and never
    calls ``order_send``. The active account must already pass AURA's DEMO guard.
    """

    normalized_symbol = symbol.strip()
    if not normalized_symbol or len(normalized_symbol) > 120:
        raise ValueError("symbol must contain 1-120 characters")
    effective_protection = protection or ProtectedMT5DemoConfig()
    gateway = OfficialMT5Gateway()
    try:
        account = gateway.connect_current_demo_session()
        raw_symbol = gateway.symbol_info(normalized_symbol)
        if raw_symbol is None:
            raise RuntimeError(f"MT5 symbol_info failed for {normalized_symbol}")
        symbol_data = _asdict(raw_symbol)
        if int(symbol_data.get("trade_mode", 0)) == 0:
            raise RuntimeError(f"MT5 symbol is disabled/non-tradable: {normalized_symbol}")
        if not bool(symbol_data.get("visible", True)):
            if not gateway.symbol_select(normalized_symbol, True):
                raise RuntimeError(f"MT5 could not select {normalized_symbol} in MarketWatch")
            raw_symbol = gateway.symbol_info(normalized_symbol)
            if raw_symbol is None:
                raise RuntimeError(f"MT5 symbol_info failed after selecting {normalized_symbol}")
            symbol_data = _asdict(raw_symbol)

        volume = Decimal(str(symbol_data.get("volume_min", 0)))
        if volume <= 0:
            raise RuntimeError(f"MT5 returned invalid minimum volume for {normalized_symbol}")
        tick = gateway.symbol_info_tick(normalized_symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick failed for {normalized_symbol}")
        tick_data = _asdict(tick)
        price = Decimal(str(tick_data["ask"] if side == Side.BUY else tick_data["bid"]))
        if price <= 0:
            raise RuntimeError(f"MT5 returned non-positive price for {normalized_symbol}")

        broker = ProtectedMT5DemoBroker(gateway, config=effective_protection)
        stop, target = _protected_prices(
            symbol_data,
            side=side,
            entry=price,
            stop_bps=effective_protection.stop_bps,
            target_bps=effective_protection.target_bps,
        )
        order_type = broker._mt5_market_type(side)
        margin = gateway.order_calc_margin(
            order_type,
            normalized_symbol,
            float(volume),
            float(price),
        )
        if margin is None:
            raise RuntimeError(f"MT5 order_calc_margin failed: {gateway.last_error()}")

        request: dict[str, Any] = {
            "action": gateway.constant("TRADE_ACTION_DEAL"),
            "symbol": normalized_symbol,
            "volume": float(volume),
            "type": order_type,
            "sl": float(stop),
            "tp": float(target),
            "deviation": effective_protection.deviation_points,
            "magic": effective_protection.magic,
            "comment": "AURA:CHECK",
            "type_time": gateway.constant("ORDER_TIME_GTC"),
            "type_filling": broker._resolve_filling(symbol_data),
        }
        if int(symbol_data.get("trade_exemode", -1)) != gateway.constant(
            "SYMBOL_TRADE_EXECUTION_MARKET"
        ):
            request["price"] = float(price)

        check = gateway.order_check(request)
        if check is None:
            raise RuntimeError(f"MT5 order_check returned None: {gateway.last_error()}")
        check_data = _asdict(check)
        retcode = int(check_data.get("retcode", -1))
        if retcode != 0:
            raise RuntimeError(
                f"MT5 order_check rejected {normalized_symbol}: "
                f"retcode={retcode} comment={check_data.get('comment', '')}"
            )

        existing = gateway.positions_get(symbol=normalized_symbol)
        if existing is None:
            raise RuntimeError(f"MT5 positions_get failed: {gateway.last_error()}")
        aura_positions = [
            row
            for row in existing
            if int(_asdict(row).get("magic", 0)) == effective_protection.magic
        ]
        return {
            "ok": True,
            "execution_ready": True,
            "demo_verified": True,
            "account": _account_payload(account),
            "symbol": normalized_symbol,
            "side": side.value,
            "minimum_volume": str(volume),
            "entry_price": str(price),
            "native_stop": str(stop),
            "native_target": str(target),
            "margin_required": str(Decimal(str(margin))),
            "margin_free": str(account.margin_free),
            "filling_mode": int(request["type_filling"]),
            "order_check_retcode": retcode,
            "order_check_comment": str(check_data.get("comment", "")),
            "existing_aura_positions": len(aura_positions),
            "pyramiding_would_be_blocked": bool(aura_positions),
            "order_check_attempted": True,
            "order_submission_attempted": False,
            "real_money_enabled": False,
        }
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {
            "ok": False,
            "execution_ready": False,
            "demo_verified": False,
            "symbol": normalized_symbol,
            "error": str(exc),
            "order_check_attempted": True,
            "order_submission_attempted": False,
            "real_money_enabled": False,
        }
    finally:
        gateway.shutdown()


def _account_payload(account: Any) -> dict[str, str]:
    return {
        "login_last4": str(account.login)[-4:],
        "server": str(account.server),
        "currency": str(account.currency),
        "balance": str(account.balance),
        "equity": str(account.equity),
        "margin": str(account.margin),
        "margin_free": str(account.margin_free),
    }


def _asdict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    return dict(vars(value))
