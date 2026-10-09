"""Executable research setups shared by the owner UI and advisory strategy desk."""

from __future__ import annotations

from dataclasses import dataclass

from aura.research.strategy_factory import ExitPrimitive, StrategyBlueprint, StrategyPrimitive


@dataclass(frozen=True, slots=True)
class ResearchSetup:
    key: str
    name: str
    family: str
    thesis: str
    entries: tuple[str, ...]
    confirmations: tuple[str, ...]

    def blueprint(self) -> StrategyBlueprint:
        return StrategyBlueprint(
            family=f"desk:{self.key}",
            market_scope=("ALL",),
            timeframe_scope=("1m", "5m", "15m", "1h", "4h", "1d"),
            entries=tuple(StrategyPrimitive(item) for item in self.entries),
            confirmations=tuple(StrategyPrimitive(item) for item in self.confirmations),
            exits=(
                ExitPrimitive.ATR_STOP,
                ExitPrimitive.RISK_REWARD_TARGET,
                ExitPrimitive.TIME_STOP,
            ),
            parameters={
                "ema_fast": 8,
                "ema_slow": 21,
                "minimum_confirmations": len(self.confirmations),
                "structure_lookback": 13,
                "max_choppiness": 61.8,
                "min_choppiness": 55.0,
            },
        )

    def owner_template(self) -> dict:
        return {
            "name": self.name,
            "thesis": self.thesis,
            "family": self.family,
            "markets": ["XAUUSD", "BTCUSD", "USOIL", "EURUSD"],
            "timeframes": ["5m", "15m", "1h"],
            "entries": list(self.entries),
            "confirmations": list(self.confirmations),
            "exits": ["atr_stop", "risk_reward_target", "time_stop"],
            "stage": "RESEARCH",
            "performance_verified": False,
        }


STRATEGY_SETUPS = (
    ResearchSetup(
        "ema",
        "EMA momentum",
        "trend",
        "EMA continuation with momentum and chop rejection.",
        ("ema_trend",),
        ("rsi_state", "chop_filter"),
    ),
    ResearchSetup(
        "macd",
        "MACD momentum",
        "momentum",
        "Momentum continuation in a directional regime; entries can lag.",
        ("macd_momentum",),
        ("regime", "chop_filter"),
    ),
    ResearchSetup(
        "bollinger",
        "Bollinger reversion",
        "reversion",
        "Band extremes in a range; sustained trends invalidate the thesis.",
        ("bollinger_reversion",),
        ("range_filter",),
    ),
    ResearchSetup(
        "keltner",
        "Keltner breakout",
        "breakout",
        "Volatility breakout confirmed by participation; false breaks remain possible.",
        ("keltner_breakout",),
        ("relative_volume", "chop_filter"),
    ),
    ResearchSetup(
        "sweep",
        "Liquidity sweep",
        "structure",
        "Closed-candle sweep and reclaim near a range extreme; OHLC liquidity proxy.",
        ("liquidity_sweep",),
        ("premium_discount",),
    ),
    ResearchSetup(
        "supertrend",
        "Supertrend continuation",
        "trend",
        "ATR-band trend continuation with chop rejection.",
        ("supertrend",),
        ("chop_filter",),
    ),
    ResearchSetup(
        "donchian",
        "Donchian breakout",
        "breakout",
        "Close beyond the prior channel with participation; current bar excluded from channel.",
        ("donchian_breakout",),
        ("relative_volume", "chop_filter"),
    ),
    ResearchSetup(
        "orderblock",
        "Order-block retest",
        "structure",
        "First reclaim of an unconsumed opposite candle after a confirmed range break; OHLC proxy.",
        ("order_block",),
        ("premium_discount",),
    ),
    ResearchSetup(
        "fvg",
        "Fair-value gap",
        "structure",
        "Three closed candles form a causal gap during directional expansion.",
        ("fair_value_gap",),
        ("regime",),
    ),
    ResearchSetup(
        "bos",
        "Structure breakout",
        "structure",
        "Close beyond prior structure, with participation and chop rejection.",
        ("bos_choch",),
        ("relative_volume", "chop_filter"),
    ),
    ResearchSetup(
        "vwap",
        "VWAP participation",
        "participation",
        "Session VWAP direction with relative volume in a non-choppy market.",
        ("vwap",),
        ("relative_volume", "chop_filter"),
    ),
    ResearchSetup(
        "rsi",
        "RSI range reversion",
        "reversion",
        "Oversold/overbought reversion only in a range; extremes are not guaranteed reversals.",
        ("rsi_reversion",),
        ("range_filter",),
    ),
    ResearchSetup(
        "pivot",
        "Prior-bar pivot reclaim",
        "structure",
        "Reclaim prior-bar pivot support/resistance; these are not daily session pivots.",
        ("pivot_support_resistance",),
        ("premium_discount",),
    ),
    ResearchSetup(
        "divergence",
        "Confirmed RSI divergence",
        "reversion",
        "Price/RSI divergence at a pivot confirmed two bars later, in a range.",
        ("bollinger_reversion",),
        ("divergence", "range_filter"),
    ),
)
