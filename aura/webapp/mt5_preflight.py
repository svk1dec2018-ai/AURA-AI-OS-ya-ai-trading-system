from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from aura.data.mt5_demo import OfficialMT5Gateway
from aura.data.mt5_session import MT5_SESSION_LOCK
from aura.domain.models import Side
from aura.execution.mt5_protected_demo import (
    ProtectedMT5DemoBroker,
    ProtectedMT5DemoConfig,
    _protected_prices,
)

def mt5_demo_preflight(*, max_symbols: int = 200, query: str = "") -> dict[str, Any]:
    # The MetaTrader5 Python bridge is process-global. Serialize complete
    # connect/use/shutdown sessions so concurrent web requests cannot shut down
    # each other's terminal connection.
    with MT5_SESSION_LOCK:
        return _mt5_demo_preflight_unlocked(max_symbols=max_symbols, query=query)


def _mt5_demo_preflight_unlocked(
    *, max_symbols: int = 200, query: str = ""
) -> dict[str, Any]:
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
        priorities = ("XAUUSD", "BTCUSD", "USOIL", "EURUSD", "GBPUSD", "XAGUSD")
        matching = sorted(
            (item for item in instruments if query.strip().casefold() in (
                f"{item.venue_symbol} {metadata.get(item.venue_symbol, {}).get('description', '')} "
                f"{metadata.get(item.venue_symbol, {}).get('path', '')}"
            ).casefold()),
            key=lambda item: (_symbol_priority(item.venue_symbol, priorities), item.venue_symbol),
        )
        market_clock = _first_available_market_clock(
            gateway,
            tuple(item.venue_symbol for item in instruments),
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
            "market_clock": market_clock,
            "market_clock_ok": market_clock["ok"],
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
    with _MT5_WEB_LOCK:
        return _mt5_demo_execution_check_unlocked(symbol, side=side, protection=protection)


def _mt5_demo_execution_check_unlocked(
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

    Owner-facing canonical symbols such as ``XAUUSD`` are resolved to the exact
    broker symbol (for example ``XAUUSDm``) before the no-send broker check.
    """

    requested_symbol = symbol.strip()
    if not requested_symbol or len(requested_symbol) > 120:
        raise ValueError("symbol must contain 1-120 characters")
    resolved_symbol = requested_symbol
    effective_protection = protection or ProtectedMT5DemoConfig()
    gateway = OfficialMT5Gateway()
    try:
        account = gateway.connect_current_demo_session()
        resolved_symbol, raw_symbol = _resolve_broker_symbol(gateway, requested_symbol)
        symbol_data = _asdict(raw_symbol)
        if int(symbol_data.get("trade_mode", 0)) == 0:
            raise RuntimeError(f"MT5 symbol is disabled/non-tradable: {resolved_symbol}")
        if not bool(symbol_data.get("visible", True)):
            if not gateway.symbol_select(resolved_symbol, True):
                raise RuntimeError(f"MT5 could not select {resolved_symbol} in MarketWatch")
            raw_symbol = gateway.symbol_info(resolved_symbol)
            if raw_symbol is None:
                raise RuntimeError(f"MT5 symbol_info failed after selecting {resolved_symbol}")
            symbol_data = _asdict(raw_symbol)

        volume = Decimal(str(symbol_data.get("volume_min", 0)))
        if volume <= 0:
            raise RuntimeError(f"MT5 returned invalid minimum volume for {resolved_symbol}")
        tick = gateway.symbol_info_tick(resolved_symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick failed for {resolved_symbol}")
        tick_data = _asdict(tick)
        price = Decimal(str(tick_data["ask"] if side == Side.BUY else tick_data["bid"]))
        if price <= 0:
            raise RuntimeError(f"MT5 returned non-positive price for {resolved_symbol}")

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
            resolved_symbol,
            float(volume),
            float(price),
        )
        if margin is None:
            raise RuntimeError(f"MT5 order_calc_margin failed: {gateway.last_error()}")

        request: dict[str, Any] = {
            "action": gateway.constant("TRADE_ACTION_DEAL"),
            "symbol": resolved_symbol,
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
                f"MT5 order_check rejected {resolved_symbol}: "
                f"retcode={retcode} comment={check_data.get('comment', '')}"
            )

        existing = gateway.positions_get(symbol=resolved_symbol)
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
            "requested_symbol": requested_symbol,
            "symbol": resolved_symbol,
            "symbol_resolved": resolved_symbol.casefold() != requested_symbol.casefold(),
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
            "requested_symbol": requested_symbol,
            "symbol": resolved_symbol,
            "error": str(exc),
            "order_check_attempted": True,
            "order_submission_attempted": False,
            "real_money_enabled": False,
        }
    finally:
        gateway.shutdown()


def _resolve_broker_symbol(
    gateway: OfficialMT5Gateway,
    requested_symbol: str,
) -> tuple[str, Any]:
    """Resolve a canonical owner symbol to an exact tradable MT5 broker symbol."""

    direct = gateway.symbol_info(requested_symbol)
    if direct is not None and int(_asdict(direct).get("trade_mode", 0)) != 0:
        return requested_symbol, direct

    raw_symbols = gateway.symbols_get()
    if raw_symbols is None:
        if direct is not None:
            return requested_symbol, direct
        raise RuntimeError(f"MT5 symbol_info failed for {requested_symbol}")

    requested_key = requested_symbol.casefold()
    candidates: list[tuple[int, int, int, str, str]] = []
    for row in raw_symbols:
        data = _asdict(row)
        name = str(data.get("name") or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key == requested_key:
            match_rank = 0
        elif key.startswith(requested_key):
            match_rank = 1
        else:
            continue
        trade_mode = int(data.get("trade_mode", 0) or 0)
        candidates.append((0 if trade_mode != 0 else 1, match_rank, len(name), key, name))

    for _disabled, _match_rank, _length, _key, name in sorted(candidates):
        info = gateway.symbol_info(name)
        if info is None:
            continue
        if int(_asdict(info).get("trade_mode", 0)) == 0:
            continue
        return name, info

    if direct is not None:
        return requested_symbol, direct
    raise RuntimeError(
        f"MT5 symbol_info failed for {requested_symbol}; no tradable broker alias found"
    )


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


def _market_clock_payload(gateway: OfficialMT5Gateway, symbol: str) -> dict[str, Any]:
    """Detect broker timestamps that would leak future data into decisions."""

    if not symbol:
        return {"ok": False, "error": "no tradable symbol available for clock check"}
    tick = gateway.symbol_info_tick(symbol)
    if tick is None:
        return {"ok": False, "symbol": symbol, "error": "broker tick unavailable"}
    source = _asdict(tick)
    raw_seconds = source.get("time")
    if raw_seconds in (None, 0):
        return {"ok": False, "symbol": symbol, "error": "broker tick timestamp unavailable"}
    observed_at = datetime.now(UTC)
    broker_time = datetime.fromtimestamp(float(raw_seconds), UTC)
    future_skew_seconds = max(0, int((broker_time - observed_at).total_seconds()))
    ok = future_skew_seconds <= 300
    return {
        "ok": ok,
        "symbol": symbol,
        "broker_time": broker_time.isoformat(),
        "observed_at": observed_at.isoformat(),
        "future_skew_seconds": future_skew_seconds,
        "error": None if ok else "broker market timestamp is more than 5 minutes in the future",
    }


def _first_available_market_clock(
    gateway: OfficialMT5Gateway,
    symbols: tuple[str, ...],
) -> dict[str, Any]:
    """Use an active liquid contract, including broker-suffixed symbols.

    Brokers such as Exness expose ``XAUUSDm``/``EURUSDm`` rather than the bare
    canonical name.  An alphabetically first stock can legitimately have no
    tick outside its session, so an unavailable tick is not sufficient clock
    evidence and must fall through to the next preferred contract.
    """

    priorities = ("XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USOIL", "XAGUSD")
    ranked = sorted(
        symbols,
        key=lambda symbol: (_symbol_priority(symbol, priorities), symbol),
    )
    last = {"ok": False, "error": "no tradable symbol available for clock check"}
    for symbol in ranked:
        result = _market_clock_payload(gateway, symbol)
        last = result
        if result.get("broker_time") is not None:
            return result
    return last


def _symbol_priority(symbol: str, priorities: tuple[str, ...]) -> int:
    upper = symbol.upper()
    return next(
        (
            index
            for index, prefix in enumerate(priorities)
            if upper == prefix or upper.startswith(prefix)
        ),
        len(priorities),
    )


def _asdict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    return dict(vars(value))
