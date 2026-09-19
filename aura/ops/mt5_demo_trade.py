from __future__ import annotations

import argparse
import json
import time
from decimal import Decimal
from typing import Any

from aura.data.mt5_demo import OfficialMT5Gateway, load_mt5_demo_credentials_from_env

_MAGIC = 560026


def _asdict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    return dict(vars(value))


def _resolve_symbol(gateway: OfficialMT5Gateway, requested: str) -> str:
    rows = gateway.symbols_get()
    if rows is None:
        raise RuntimeError(f"MT5 symbols_get failed: {gateway.last_error()}")
    requested_upper = requested.upper()
    candidates: list[tuple[int, str]] = []
    for row in rows:
        source = _asdict(row)
        name = str(source.get("name", "")).strip()
        if not name:
            continue
        upper = name.upper()
        compact = "".join(ch for ch in upper if ch.isalnum())
        requested_compact = "".join(ch for ch in requested_upper if ch.isalnum())
        score = -1
        if upper == requested_upper:
            score = 120
        elif compact == requested_compact:
            score = 115
        elif compact.startswith(requested_compact):
            score = 100
        elif requested_compact in compact:
            score = 90
        if score >= 0:
            if int(source.get("trade_mode", 0)) != 0:
                score += 30
            candidates.append((score, name))
    if not candidates:
        raise RuntimeError(f"No tradable MT5 symbol matched {requested}")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def _fill_mode(gateway: OfficialMT5Gateway, symbol: dict[str, Any]) -> int:
    mode = int(symbol.get("filling_mode", 0))
    if mode & gateway.constant("SYMBOL_FILLING_IOC"):
        return gateway.constant("ORDER_FILLING_IOC")
    if mode & gateway.constant("SYMBOL_FILLING_FOK"):
        return gateway.constant("ORDER_FILLING_FOK")
    if int(symbol.get("trade_exemode", -1)) != gateway.constant(
        "SYMBOL_TRADE_EXECUTION_MARKET"
    ):
        return gateway.constant("ORDER_FILLING_RETURN")
    raise RuntimeError("MT5 symbol exposes no safe supported filling policy")


def _protected_prices(
    symbol: dict[str, Any],
    *,
    side: str,
    entry: Decimal,
    stop_bps: Decimal,
    target_bps: Decimal,
) -> tuple[Decimal, Decimal]:
    point = Decimal(str(symbol.get("point", 0)))
    if point <= 0:
        raise RuntimeError("MT5 symbol point must be positive")
    minimum_points = max(int(symbol.get("trade_stops_level", 0)), 1)
    broker_min_distance = point * Decimal(minimum_points + 2)
    stop_distance = max(entry * stop_bps / Decimal(10000), broker_min_distance)
    target_distance = max(entry * target_bps / Decimal(10000), broker_min_distance)
    digits = int(symbol.get("digits", 5))
    quantum = Decimal(1).scaleb(-digits)
    if side == "BUY":
        stop = entry - stop_distance
        target = entry + target_distance
    else:
        stop = entry + stop_distance
        target = entry - target_distance
    if stop <= 0 or target <= 0:
        raise RuntimeError("calculated native protection price is invalid")
    return stop.quantize(quantum), target.quantize(quantum)


def _find_aura_positions(gateway: OfficialMT5Gateway, symbol: str) -> list[Any]:
    rows = gateway.positions_get(symbol=symbol)
    if rows is None:
        raise RuntimeError(f"MT5 positions_get failed: {gateway.last_error()}")
    return [row for row in rows if int(_asdict(row).get("magic", 0)) == _MAGIC]


def _close_position(
    gateway: OfficialMT5Gateway,
    position: Any,
    symbol_data: dict[str, Any],
) -> dict[str, Any]:
    source = _asdict(position)
    symbol = str(source["symbol"])
    volume = Decimal(str(source["volume"]))
    position_type = int(source["type"])
    tick = gateway.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"missing close tick for {symbol}")
    tick_data = _asdict(tick)
    if position_type == gateway.constant("POSITION_TYPE_BUY"):
        order_type = gateway.constant("ORDER_TYPE_SELL")
        price = Decimal(str(tick_data["bid"]))
    elif position_type == gateway.constant("POSITION_TYPE_SELL"):
        order_type = gateway.constant("ORDER_TYPE_BUY")
        price = Decimal(str(tick_data["ask"]))
    else:
        raise RuntimeError(f"unknown MT5 position type {position_type}")
    request: dict[str, Any] = {
        "action": gateway.constant("TRADE_ACTION_DEAL"),
        "position": int(source["ticket"]),
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type,
        "deviation": 20,
        "magic": _MAGIC,
        "comment": "AURA-DEMO-CLOSE",
        "type_time": gateway.constant("ORDER_TIME_GTC"),
        "type_filling": _fill_mode(gateway, symbol_data),
    }
    if int(symbol_data.get("trade_exemode", -1)) != gateway.constant(
        "SYMBOL_TRADE_EXECUTION_MARKET"
    ):
        request["price"] = float(price)
    check = gateway.order_check(request)
    if check is None:
        raise RuntimeError(f"MT5 close order_check returned None: {gateway.last_error()}")
    check_data = _asdict(check)
    if int(check_data.get("retcode", -1)) != 0:
        raise RuntimeError(
            f"MT5 close order_check rejected: retcode={check_data.get('retcode')} "
            f"comment={check_data.get('comment', '')}"
        )
    result = gateway.order_send(request)
    if result is None:
        raise RuntimeError(f"MT5 close order_send returned None: {gateway.last_error()}")
    result_data = _asdict(result)
    accepted = {
        gateway.constant("TRADE_RETCODE_DONE"),
        gateway.constant("TRADE_RETCODE_DONE_PARTIAL"),
        gateway.constant("TRADE_RETCODE_PLACED"),
    }
    if int(result_data.get("retcode", -1)) not in accepted:
        raise RuntimeError(
            f"MT5 close rejected: retcode={result_data.get('retcode')} "
            f"comment={result_data.get('comment', '')}"
        )
    return result_data


def execute_demo_trade(
    gateway: OfficialMT5Gateway,
    *,
    requested_symbol: str,
    side: str,
    volume: Decimal | None,
    stop_bps: Decimal,
    target_bps: Decimal,
    auto_close_seconds: int | None,
) -> dict[str, Any]:
    symbol_name = _resolve_symbol(gateway, requested_symbol)
    raw_symbol = gateway.symbol_info(symbol_name)
    if raw_symbol is None:
        raise RuntimeError(f"MT5 symbol_info failed for {symbol_name}")
    symbol = _asdict(raw_symbol)
    if int(symbol.get("trade_mode", 0)) == 0:
        raise RuntimeError(f"{symbol_name} is disabled/non-tradable")
    if not bool(symbol.get("visible", True)) and not gateway.symbol_select(symbol_name, True):
        raise RuntimeError(f"could not enable {symbol_name} in Market Watch")

    existing = _find_aura_positions(gateway, symbol_name)
    if existing:
        raise RuntimeError(
            f"AURA DEMO safety block: {symbol_name} already has {len(existing)} AURA position(s)"
        )

    minimum = Decimal(str(symbol.get("volume_min", 0)))
    maximum = Decimal(str(symbol.get("volume_max", 0)))
    step = Decimal(str(symbol.get("volume_step", 0)))
    quantity = volume or minimum
    if minimum <= 0 or maximum <= 0 or step <= 0:
        raise RuntimeError("MT5 symbol has invalid volume metadata")
    if not minimum <= quantity <= maximum:
        raise ValueError(f"volume {quantity} outside [{minimum}, {maximum}]")
    units = (quantity - minimum) / step
    if units != units.to_integral_value():
        raise ValueError(f"volume {quantity} is not aligned to step {step}")

    tick = gateway.symbol_info_tick(symbol_name)
    if tick is None:
        raise RuntimeError(f"no live tick for {symbol_name}")
    tick_data = _asdict(tick)
    is_buy = side == "BUY"
    entry = Decimal(str(tick_data["ask"] if is_buy else tick_data["bid"]))
    if entry <= 0:
        raise RuntimeError("MT5 returned non-positive entry price")
    stop, target = _protected_prices(
        symbol,
        side=side,
        entry=entry,
        stop_bps=stop_bps,
        target_bps=target_bps,
    )
    order_type = gateway.constant("ORDER_TYPE_BUY" if is_buy else "ORDER_TYPE_SELL")
    request: dict[str, Any] = {
        "action": gateway.constant("TRADE_ACTION_DEAL"),
        "symbol": symbol_name,
        "volume": float(quantity),
        "type": order_type,
        "sl": float(stop),
        "tp": float(target),
        "deviation": 20,
        "magic": _MAGIC,
        "comment": "AURA-DEMO",
        "type_time": gateway.constant("ORDER_TIME_GTC"),
        "type_filling": _fill_mode(gateway, symbol),
    }
    if int(symbol.get("trade_exemode", -1)) != gateway.constant(
        "SYMBOL_TRADE_EXECUTION_MARKET"
    ):
        request["price"] = float(entry)

    margin = gateway.order_calc_margin(order_type, symbol_name, float(quantity), float(entry))
    if margin is None:
        raise RuntimeError(f"MT5 order_calc_margin failed: {gateway.last_error()}")
    check = gateway.order_check(request)
    if check is None:
        raise RuntimeError(f"MT5 order_check returned None: {gateway.last_error()}")
    check_data = _asdict(check)
    if int(check_data.get("retcode", -1)) != 0:
        raise RuntimeError(
            f"MT5 order_check rejected: retcode={check_data.get('retcode')} "
            f"comment={check_data.get('comment', '')}"
        )

    result = gateway.order_send(request)
    if result is None:
        raise RuntimeError(f"MT5 order_send returned None: {gateway.last_error()}")
    result_data = _asdict(result)
    accepted = {
        gateway.constant("TRADE_RETCODE_DONE"),
        gateway.constant("TRADE_RETCODE_DONE_PARTIAL"),
        gateway.constant("TRADE_RETCODE_PLACED"),
    }
    if int(result_data.get("retcode", -1)) not in accepted:
        raise RuntimeError(
            f"MT5 order_send rejected: retcode={result_data.get('retcode')} "
            f"comment={result_data.get('comment', '')}"
        )

    payload: dict[str, Any] = {
        "demo_only": True,
        "symbol": symbol_name,
        "side": side,
        "volume": str(quantity),
        "entry_reference": str(entry),
        "native_stop_loss": str(stop),
        "native_take_profit": str(target),
        "margin_required": str(margin),
        "entry_retcode": int(result_data.get("retcode", -1)),
        "entry_order": int(result_data.get("order", 0)),
        "auto_close_seconds": auto_close_seconds,
        "closed_by_runner": False,
    }

    if auto_close_seconds is not None:
        if auto_close_seconds <= 0:
            raise ValueError("auto_close_seconds must be positive")
        time.sleep(auto_close_seconds)
        positions = _find_aura_positions(gateway, symbol_name)
        close_results = [_close_position(gateway, item, symbol) for item in positions]
        payload["closed_by_runner"] = True
        payload["close_results"] = [
            {
                "retcode": int(item.get("retcode", -1)),
                "order": int(item.get("order", 0)),
            }
            for item in close_results
        ]
        time.sleep(1)
        payload["flat_after_close"] = not _find_aura_positions(gateway, symbol_name)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Protected generic MT5 DEMO trade tool")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", choices=("BUY", "SELL"), required=True)
    parser.add_argument("--volume", default=None)
    parser.add_argument("--stop-bps", default="50")
    parser.add_argument("--target-bps", default="100")
    parser.add_argument("--auto-close-seconds", type=int, default=30)
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="leave the protected DEMO position open; native SL/TP remain active",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    gateway = OfficialMT5Gateway()
    try:
        credentials = load_mt5_demo_credentials_from_env()
        gateway.connect_demo(credentials)
        payload = execute_demo_trade(
            gateway,
            requested_symbol=args.symbol,
            side=args.side,
            volume=Decimal(args.volume) if args.volume else None,
            stop_bps=Decimal(args.stop_bps),
            target_bps=Decimal(args.target_bps),
            auto_close_seconds=None if args.keep_open else args.auto_close_seconds,
        )
        print(json.dumps({"ok": True, **payload}, indent=2, sort_keys=True))
        return 0
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "demo_only": True,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    finally:
        gateway.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
