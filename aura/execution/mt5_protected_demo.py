from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aura.data.mt5_demo import OfficialMT5Gateway
from aura.domain.models import Fill, NormalizedCandle, OrderRequest, OrderStatus, Side
from aura.execution.demo_guard import DemoExecutionGuard
from aura.execution.mt5_demo_broker import MT5DemoBroker, MT5DemoBrokerConfig
from aura.execution.reconciliation import BrokerOrderSnapshot, BrokerPositionSnapshot


@dataclass(slots=True, frozen=True)
class ProtectedMT5DemoConfig:
    """Fail-closed protection for autonomous MT5 DEMO execution."""

    magic: int = 560026
    deviation_points: int = 20
    stop_bps: Decimal = Decimal(35)
    target_bps: Decimal = Decimal(70)
    block_pyramiding: bool = True
    recovery_lookback_seconds: int = 604800

    def __post_init__(self) -> None:
        if self.magic <= 0:
            raise ValueError("magic must be positive")
        if self.deviation_points < 0:
            raise ValueError("deviation_points cannot be negative")
        if self.stop_bps <= 0 or self.target_bps <= 0:
            raise ValueError("native stop/target distances must be positive")
        if self.recovery_lookback_seconds <= 0:
            raise ValueError("recovery_lookback_seconds must be positive")


class ProtectedMT5DemoBroker(MT5DemoBroker):
    """DEMO-only MT5 broker with mandatory native SL/TP and AURA isolation.

    Entries are protected at the broker, pyramiding is blocked by default, and
    strategy exit orders are allowed only when they reduce a single AURA-owned
    position. Reconciliation sees only orders/positions carrying AURA's magic
    number, so unrelated manual positions are never managed by this adapter.
    """

    def __init__(
        self,
        gateway: OfficialMT5Gateway,
        *,
        config: ProtectedMT5DemoConfig | None = None,
    ) -> None:
        self.protected_config = config or ProtectedMT5DemoConfig()
        super().__init__(
            gateway,
            config=MT5DemoBrokerConfig(
                magic=self.protected_config.magic,
                deviation_points=self.protected_config.deviation_points,
                history_lookback_seconds=self.protected_config.recovery_lookback_seconds,
            ),
        )

    def restore_orders(self, orders: Iterable[OrderRequest]) -> None:
        """Rebuild client-token mappings from the append-only financial WAL."""
        for order in orders:
            token = hashlib.sha1(order.client_order_id.encode("utf-8")).hexdigest()[:12]
            self._order_by_token[token] = order

    async def on_candle(self, candle: NormalizedCandle) -> list[Fill]:
        """Poll broker-origin fills on the same cadence as closed-candle decisions."""
        if not candle.closed:
            raise ValueError("protected MT5 DEMO broker only accepts closed candles")
        self._require_connected()
        return list(await asyncio.to_thread(self._poll_fills_sync))

    def open_order_snapshots(self) -> list[BrokerOrderSnapshot]:
        rows = self.gateway.orders_get()
        if rows is None:
            raise RuntimeError(f"MT5 orders_get failed: {self.gateway.last_error()}")
        snapshots: list[BrokerOrderSnapshot] = []
        for row in rows:
            source = _asdict(row)
            if int(source.get("magic", 0)) != self.protected_config.magic:
                continue
            ticket = int(source.get("ticket", 0))
            mapped = self._order_by_ticket.get(ticket)
            if mapped is None:
                client_order_id = f"aura-mt5:{ticket}"
                symbol = str(source.get("symbol", ""))
                side = self._side_from_order_type(int(source.get("type", -1)))
                initial = Decimal(str(source.get("volume_initial", 0)))
            else:
                client_order_id = mapped.client_order_id
                symbol = mapped.symbol
                side = mapped.side
                initial = mapped.quantity
            if initial <= 0:
                continue
            remaining = Decimal(str(source.get("volume_current", initial)))
            filled = max(Decimal(0), initial - remaining)
            snapshots.append(
                BrokerOrderSnapshot(
                    broker_order_id=str(ticket),
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side,
                    quantity=initial,
                    filled_quantity=filled,
                    status=(
                        OrderStatus.PARTIALLY_FILLED
                        if filled > 0
                        else OrderStatus.SUBMITTED
                    ),
                )
            )
        return snapshots

    def position_snapshots(self) -> list[BrokerPositionSnapshot]:
        rows = self.gateway.positions_get()
        if rows is None:
            raise RuntimeError(f"MT5 positions_get failed: {self.gateway.last_error()}")
        quantities: dict[str, Decimal] = {}
        for row in rows:
            source = _asdict(row)
            if int(source.get("magic", 0)) != self.protected_config.magic:
                continue
            symbol = str(source.get("symbol", ""))
            volume = Decimal(str(source.get("volume", 0)))
            if not symbol or volume <= 0:
                continue
            position_type = int(source.get("type", -1))
            if position_type == self.gateway.constant("POSITION_TYPE_BUY"):
                signed = volume
            elif position_type == self.gateway.constant("POSITION_TYPE_SELL"):
                signed = -volume
            else:
                raise RuntimeError(f"unknown MT5 position type: {position_type}")
            quantities[symbol] = quantities.get(symbol, Decimal(0)) + signed
        return [
            BrokerPositionSnapshot(symbol=symbol, quantity=quantity)
            for symbol, quantity in sorted(quantities.items())
            if quantity != 0
        ]

    def _submit_market_sync(self, order: OrderRequest) -> int:
        info = self.gateway.account_info()
        if info is None:
            raise RuntimeError(f"MT5 account_info failed: {self.gateway.last_error()}")
        DemoExecutionGuard.assert_mt5_demo_account(info)

        raw_symbol = self.gateway.symbol_info(order.symbol)
        if raw_symbol is None:
            raise RuntimeError(f"MT5 symbol_info failed for {order.symbol}")
        symbol = _asdict(raw_symbol)
        if int(symbol.get("trade_mode", 0)) == 0:
            raise RuntimeError(f"MT5 symbol is disabled/non-tradable: {order.symbol}")
        if not bool(symbol.get("visible", True)) and not self.gateway.symbol_select(order.symbol, True):
            raise RuntimeError(f"MT5 could not select {order.symbol} in MarketWatch")
        self._validate_volume(order.quantity, symbol)

        existing = self.gateway.positions_get(symbol=order.symbol)
        if existing is None:
            raise RuntimeError(f"MT5 positions_get failed: {self.gateway.last_error()}")
        aura_positions = [
            row
            for row in existing
            if int(_asdict(row).get("magic", 0)) == self.protected_config.magic
        ]
        is_exit = False
        position_ticket: int | None = None
        if aura_positions:
            if len(aura_positions) != 1:
                raise RuntimeError(
                    f"AURA DEMO safety block: {order.symbol} has multiple AURA positions"
                )
            position = _asdict(aura_positions[0])
            position_side = _position_side(self.gateway, position)
            position_volume = Decimal(str(position.get("volume", 0)))
            is_exit = order.side != position_side
            if not is_exit and self.protected_config.block_pyramiding:
                raise RuntimeError(
                    f"AURA DEMO safety block: pyramiding is disabled for {order.symbol}"
                )
            if is_exit:
                if position_volume <= 0:
                    raise RuntimeError("AURA DEMO position has invalid volume")
                if order.quantity > position_volume:
                    raise RuntimeError(
                        f"AURA DEMO exit volume {order.quantity} exceeds open volume "
                        f"{position_volume} for {order.symbol}"
                    )
                position_ticket = int(position.get("ticket", 0))
                if position_ticket <= 0:
                    raise RuntimeError("AURA DEMO position is missing a valid ticket")

        tick = self.gateway.symbol_info_tick(order.symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick failed for {order.symbol}")
        tick_data = _asdict(tick)
        entry = Decimal(
            str(tick_data["ask"] if order.side == Side.BUY else tick_data["bid"])
        )
        if entry <= 0:
            raise RuntimeError(f"MT5 returned non-positive tradable price for {order.symbol}")

        token = hashlib.sha1(order.client_order_id.encode("utf-8")).hexdigest()[:12]
        request: dict[str, Any] = {
            "action": self.gateway.constant("TRADE_ACTION_DEAL"),
            "symbol": order.symbol,
            "volume": float(order.quantity),
            "type": self._mt5_market_type(order.side),
            "deviation": self.protected_config.deviation_points,
            "magic": self.protected_config.magic,
            "comment": f"{self.config.comment_prefix}:{token}",
            "type_time": self.gateway.constant("ORDER_TIME_GTC"),
            "type_filling": self._resolve_filling(symbol),
        }
        if is_exit:
            assert position_ticket is not None
            request["position"] = position_ticket
        else:
            stop, target = _protected_prices(
                symbol,
                side=order.side,
                entry=entry,
                stop_bps=self.protected_config.stop_bps,
                target_bps=self.protected_config.target_bps,
            )
            request["sl"] = float(stop)
            request["tp"] = float(target)
        if int(symbol.get("trade_exemode", -1)) != self.gateway.constant(
            "SYMBOL_TRADE_EXECUTION_MARKET"
        ):
            request["price"] = float(entry)

        check = self.gateway.order_check(request)
        if check is None:
            raise RuntimeError(f"MT5 order_check returned None: {self.gateway.last_error()}")
        check_data = _asdict(check)
        if int(check_data.get("retcode", -1)) != 0:
            raise RuntimeError(
                f"MT5 order_check rejected {order.symbol}: "
                f"retcode={check_data.get('retcode')} comment={check_data.get('comment', '')}"
            )

        result = self.gateway.order_send(request)
        if result is None:
            raise RuntimeError(f"MT5 order_send returned None: {self.gateway.last_error()}")
        result_data = _asdict(result)
        accepted = {
            self.gateway.constant("TRADE_RETCODE_DONE"),
            self.gateway.constant("TRADE_RETCODE_DONE_PARTIAL"),
            self.gateway.constant("TRADE_RETCODE_PLACED"),
        }
        retcode = int(result_data.get("retcode", -1))
        if retcode not in accepted:
            raise RuntimeError(
                f"MT5 order_send rejected {order.symbol}: "
                f"retcode={retcode} comment={result_data.get('comment', '')}"
            )
        ticket = int(result_data.get("order", 0))
        if ticket <= 0:
            raise RuntimeError("MT5 accepted request without returning an order ticket")
        self._order_by_ticket[ticket] = order
        self._order_by_token[token] = order
        return ticket


def _position_side(gateway: OfficialMT5Gateway, position: dict[str, Any]) -> Side:
    position_type = int(position.get("type", -1))
    if position_type == gateway.constant("POSITION_TYPE_BUY"):
        return Side.BUY
    if position_type == gateway.constant("POSITION_TYPE_SELL"):
        return Side.SELL
    raise RuntimeError(f"unknown MT5 position type: {position_type}")


def _protected_prices(
    symbol: dict[str, Any],
    *,
    side: Side,
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
    if side == Side.BUY:
        stop = entry - stop_distance
        target = entry + target_distance
    else:
        stop = entry + stop_distance
        target = entry - target_distance
    if stop <= 0 or target <= 0:
        raise RuntimeError("calculated native protection price is invalid")
    return stop.quantize(quantum), target.quantize(quantum)


def _asdict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    return dict(vars(value))
