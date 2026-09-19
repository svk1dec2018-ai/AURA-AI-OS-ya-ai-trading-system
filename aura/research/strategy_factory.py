from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aura.research.autonomy import ResearchHypothesis
from aura.research.lifecycle import StrategyStage, StrategyVersion


class StrategyPrimitive(str, Enum):
    EMA_TREND = "ema_trend"
    RSI_STATE = "rsi_state"
    MACD_MOMENTUM = "macd_momentum"
    BOLLINGER_REVERSION = "bollinger_reversion"
    KELTNER_BREAKOUT = "keltner_breakout"
    SUPERTREND = "supertrend"
    ATR_VOLATILITY = "atr_volatility"
    PIVOT_SUPPORT_RESISTANCE = "pivot_support_resistance"
    DIVERGENCE = "divergence"
    VWAP = "vwap"
    RELATIVE_VOLUME = "relative_volume"
    OBV_VPT = "obv_vpt"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    BOS_CHOCH = "bos_choch"
    FAIR_VALUE_GAP = "fair_value_gap"
    ORDER_BLOCK = "order_block"
    PREMIUM_DISCOUNT = "premium_discount"
    SESSION_CONTEXT = "session_context"
    HTF_BIAS = "htf_bias"
    REGIME = "regime"
    FORECAST_ENSEMBLE = "forecast_ensemble"
    OPTIONS_PCR = "options_pcr"
    OPTIONS_IV_SKEW = "options_iv_skew"
    OPTIONS_GREEKS = "options_greeks"
    OPEN_INTEREST = "open_interest"
    FUNDING = "funding"
    LIQUIDATIONS = "liquidations"
    MACRO_NEWS = "macro_news"
    CROSS_MARKET = "cross_market"
    EXECUTION_QUALITY = "execution_quality"


class ExitPrimitive(str, Enum):
    ATR_STOP = "atr_stop"
    STRUCTURE_STOP = "structure_stop"
    RISK_REWARD_TARGET = "risk_reward_target"
    ATR_TRAILING = "atr_trailing"
    VWAP_EXIT = "vwap_exit"
    TIME_STOP = "time_stop"
    REGIME_EXIT = "regime_exit"
    PARTIAL_SCALE_OUT = "partial_scale_out"


_FORBIDDEN_PARAMETER_FRAGMENTS = frozenset(
    {
        "risk_pct",
        "risk_percent",
        "position_size",
        "quantity",
        "leverage",
        "margin",
        "max_drawdown",
        "max_daily_loss",
        "kill_switch",
        "portfolio_limit",
        "gross_exposure",
        "symbol_exposure",
        "order_notional",
        "capital_fraction",
    }
)


class StrategyBlueprint(BaseModel):
    """Research strategy description. It has no broker or portfolio-risk authority."""

    model_config = ConfigDict(frozen=True)

    family: str = Field(min_length=1)
    market_scope: tuple[str, ...]
    timeframe_scope: tuple[str, ...]
    entries: tuple[StrategyPrimitive, ...] = Field(min_length=1, max_length=6)
    confirmations: tuple[StrategyPrimitive, ...] = Field(default=(), max_length=8)
    exits: tuple[ExitPrimitive, ...] = Field(min_length=1, max_length=5)
    parameters: dict[str, int | float | str | bool] = Field(default_factory=dict)
    target_win_rate: float = Field(default=0.80, gt=0.0, lt=1.0)
    research_only: bool = True
    live_approved: bool = False

    @model_validator(mode="after")
    def validate_blueprint(self) -> StrategyBlueprint:
        if not self.market_scope or not self.timeframe_scope:
            raise ValueError("strategy blueprint requires market and timeframe scope")
        if len(set(self.entries)) != len(self.entries):
            raise ValueError("entry primitives must be unique")
        if len(set(self.confirmations)) != len(self.confirmations):
            raise ValueError("confirmation primitives must be unique")
        if len(set(self.exits)) != len(self.exits):
            raise ValueError("exit primitives must be unique")
        for key in self.parameters:
            normalized = key.lower().strip()
            if any(fragment in normalized for fragment in _FORBIDDEN_PARAMETER_FRAGMENTS):
                raise ValueError(f"strategy AI cannot own portfolio-risk parameter: {key}")
        if not self.research_only or self.live_approved:
            raise ValueError("new autonomous strategy blueprints must begin research-only")
        return self

    @property
    def content_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"target_win_rate"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def blueprint_id(self) -> str:
        return f"{self.family}:{self.content_hash[:16]}"


@dataclass(slots=True, frozen=True)
class StrategyFreedomPolicy:
    target_win_rate: float = 0.80
    max_entry_primitives: int = 3
    max_confirmation_primitives: int = 5
    max_exit_primitives: int = 3
    random_seed: int = 20260818

    def __post_init__(self) -> None:
        if not 0 < self.target_win_rate < 1:
            raise ValueError("target_win_rate must be in (0, 1)")
        if self.max_entry_primitives <= 0:
            raise ValueError("max_entry_primitives must be positive")
        if self.max_confirmation_primitives < 0 or self.max_exit_primitives <= 0:
            raise ValueError("invalid strategy component limits")


class AutonomousStrategyFactory:
    """Generate diverse immutable research strategies inside hard safety rails.

    Random search and AI-directed search share the same compiler. AI may choose
    approved alpha/confirmation/exit primitives, but it cannot provide arbitrary
    executable code or portfolio-risk parameters. Numeric parameters are generated
    only from deterministic bounded allow-lists owned by this factory.
    """

    _ENTRY_POOL = (
        StrategyPrimitive.EMA_TREND,
        StrategyPrimitive.MACD_MOMENTUM,
        StrategyPrimitive.BOLLINGER_REVERSION,
        StrategyPrimitive.KELTNER_BREAKOUT,
        StrategyPrimitive.SUPERTREND,
        StrategyPrimitive.VWAP,
        StrategyPrimitive.LIQUIDITY_SWEEP,
        StrategyPrimitive.BOS_CHOCH,
        StrategyPrimitive.FAIR_VALUE_GAP,
        StrategyPrimitive.ORDER_BLOCK,
        StrategyPrimitive.FORECAST_ENSEMBLE,
        StrategyPrimitive.OPTIONS_IV_SKEW,
        StrategyPrimitive.OPEN_INTEREST,
    )
    _CONFIRMATION_POOL = (
        StrategyPrimitive.RSI_STATE,
        StrategyPrimitive.ATR_VOLATILITY,
        StrategyPrimitive.PIVOT_SUPPORT_RESISTANCE,
        StrategyPrimitive.DIVERGENCE,
        StrategyPrimitive.RELATIVE_VOLUME,
        StrategyPrimitive.OBV_VPT,
        StrategyPrimitive.PREMIUM_DISCOUNT,
        StrategyPrimitive.SESSION_CONTEXT,
        StrategyPrimitive.HTF_BIAS,
        StrategyPrimitive.REGIME,
        StrategyPrimitive.OPTIONS_PCR,
        StrategyPrimitive.OPTIONS_GREEKS,
        StrategyPrimitive.MACRO_NEWS,
        StrategyPrimitive.CROSS_MARKET,
        StrategyPrimitive.EXECUTION_QUALITY,
    )
    _EXIT_POOL = tuple(ExitPrimitive)

    def __init__(self, policy: StrategyFreedomPolicy | None = None) -> None:
        self.policy = policy or StrategyFreedomPolicy()
        self._rng = random.Random(self.policy.random_seed)
        self._blueprints: dict[str, StrategyBlueprint] = {}

    async def generate(
        self,
        hypothesis: ResearchHypothesis,
        *,
        feedback: tuple[str, ...],
        candidate_index: int,
    ) -> StrategyVersion:
        blueprint = self.propose(
            hypothesis,
            feedback=feedback,
            candidate_index=candidate_index,
        )
        return self.register_blueprint(blueprint, candidate_index=candidate_index)

    def propose(
        self,
        hypothesis: ResearchHypothesis,
        *,
        feedback: tuple[str, ...] = (),
        candidate_index: int = 0,
    ) -> StrategyBlueprint:
        if candidate_index < 0:
            raise ValueError("candidate_index cannot be negative")
        seed = self.policy.random_seed ^ _stable_int(
            f"{hypothesis.hypothesis_id}|{candidate_index}|{'|'.join(feedback)}"
        )
        rng = random.Random(seed)

        entry_count = rng.randint(1, min(self.policy.max_entry_primitives, len(self._ENTRY_POOL)))
        confirmation_count = rng.randint(
            1 if self.policy.max_confirmation_primitives else 0,
            min(self.policy.max_confirmation_primitives, len(self._CONFIRMATION_POOL)),
        )
        exit_count = rng.randint(1, min(self.policy.max_exit_primitives, len(self._EXIT_POOL)))

        entries = tuple(sorted(rng.sample(self._ENTRY_POOL, entry_count), key=lambda item: item.value))
        confirmations = tuple(
            sorted(rng.sample(self._CONFIRMATION_POOL, confirmation_count), key=lambda item: item.value)
        )
        exits = tuple(sorted(rng.sample(self._EXIT_POOL, exit_count), key=lambda item: item.value))
        return self.propose_from_components(
            hypothesis,
            entries=entries,
            confirmations=confirmations,
            exits=exits,
            feedback=feedback,
            candidate_index=candidate_index,
            design_tag="random",
        )

    def propose_from_components(
        self,
        hypothesis: ResearchHypothesis,
        *,
        entries: tuple[StrategyPrimitive, ...],
        confirmations: tuple[StrategyPrimitive, ...],
        exits: tuple[ExitPrimitive, ...],
        feedback: tuple[str, ...] = (),
        candidate_index: int = 0,
        design_tag: str = "directed",
    ) -> StrategyBlueprint:
        """Compile selected primitives through deterministic bounded parameters."""

        if candidate_index < 0:
            raise ValueError("candidate_index cannot be negative")
        self._validate_components(entries, confirmations, exits)
        normalized_entries = tuple(sorted(entries, key=lambda item: item.value))
        normalized_confirmations = tuple(sorted(confirmations, key=lambda item: item.value))
        normalized_exits = tuple(sorted(exits, key=lambda item: item.value))
        component_key = "|".join(
            [
                *(item.value for item in normalized_entries),
                "--confirm--",
                *(item.value for item in normalized_confirmations),
                "--exit--",
                *(item.value for item in normalized_exits),
            ]
        )
        seed = self.policy.random_seed ^ _stable_int(
            f"{hypothesis.hypothesis_id}|{candidate_index}|{design_tag}|{component_key}|{'|'.join(feedback)}"
        )
        rng = random.Random(seed)
        parameters = self._parameters_for(
            normalized_entries,
            normalized_confirmations,
            normalized_exits,
            rng,
        )
        return StrategyBlueprint(
            family=f"autonomous:{hypothesis.hypothesis_id}",
            market_scope=tuple(hypothesis.market_scope or ("ALL",)),
            timeframe_scope=tuple(hypothesis.timeframe_scope or ("1m", "5m", "15m")),
            entries=normalized_entries,
            confirmations=normalized_confirmations,
            exits=normalized_exits,
            parameters=parameters,
            target_win_rate=self.policy.target_win_rate,
        )

    def register_blueprint(
        self,
        blueprint: StrategyBlueprint,
        *,
        candidate_index: int,
    ) -> StrategyVersion:
        if candidate_index < 0:
            raise ValueError("candidate_index cannot be negative")
        version = f"g{candidate_index + 1:06d}-{blueprint.content_hash[:8]}"
        strategy = StrategyVersion(
            strategy_id=blueprint.family,
            version=version,
            content_hash=blueprint.content_hash,
            stage=StrategyStage.RESEARCH,
        )
        self._blueprints[strategy.content_hash] = blueprint
        return strategy

    def blueprint_for(self, strategy: StrategyVersion) -> StrategyBlueprint:
        try:
            return self._blueprints[strategy.content_hash]
        except KeyError as exc:
            raise KeyError(f"unknown generated strategy blueprint: {strategy.content_hash}") from exc

    def _validate_components(
        self,
        entries: tuple[StrategyPrimitive, ...],
        confirmations: tuple[StrategyPrimitive, ...],
        exits: tuple[ExitPrimitive, ...],
    ) -> None:
        if not entries or len(entries) > self.policy.max_entry_primitives:
            raise ValueError("AI entry primitive count violates strategy freedom policy")
        if len(confirmations) > self.policy.max_confirmation_primitives:
            raise ValueError("AI confirmation count violates strategy freedom policy")
        if not exits or len(exits) > self.policy.max_exit_primitives:
            raise ValueError("AI exit primitive count violates strategy freedom policy")
        if len(set(entries)) != len(entries):
            raise ValueError("AI entry primitives must be unique")
        if len(set(confirmations)) != len(confirmations):
            raise ValueError("AI confirmation primitives must be unique")
        if len(set(exits)) != len(exits):
            raise ValueError("AI exit primitives must be unique")
        invalid_entries = [item.value for item in entries if item not in self._ENTRY_POOL]
        invalid_confirmations = [
            item.value for item in confirmations if item not in self._CONFIRMATION_POOL
        ]
        invalid_exits = [item.value for item in exits if item not in self._EXIT_POOL]
        if invalid_entries:
            raise ValueError(f"primitive not allowed as entry: {', '.join(invalid_entries)}")
        if invalid_confirmations:
            raise ValueError(
                f"primitive not allowed as confirmation: {', '.join(invalid_confirmations)}"
            )
        if invalid_exits:
            raise ValueError(f"primitive not allowed as exit: {', '.join(invalid_exits)}")

    @staticmethod
    def _parameters_for(
        entries: tuple[StrategyPrimitive, ...],
        confirmations: tuple[StrategyPrimitive, ...],
        exits: tuple[ExitPrimitive, ...],
        rng: random.Random,
    ) -> dict[str, int | float | str | bool]:
        components = set(entries) | set(confirmations)
        params: dict[str, int | float | str | bool] = {
            "closed_candle_only": True,
            "minimum_confirmations": max(1, min(len(confirmations), rng.randint(1, 3))),
        }
        if StrategyPrimitive.EMA_TREND in components:
            fast = rng.choice((5, 8, 9, 12, 13, 21))
            slow = rng.choice(tuple(value for value in (21, 34, 50, 55, 100) if value > fast))
            params.update(
                {"ema_fast": fast, "ema_slow": slow, "ema_trend": rng.choice((50, 100, 200))}
            )
        if StrategyPrimitive.RSI_STATE in components:
            params.update(
                {
                    "rsi_period": rng.choice((7, 9, 14, 21)),
                    "rsi_long_threshold": rng.choice((50, 52, 55, 58)),
                    "rsi_short_threshold": rng.choice((42, 45, 48, 50)),
                }
            )
        if StrategyPrimitive.MACD_MOMENTUM in components:
            params.update({"macd_fast": 12, "macd_slow": 26, "macd_signal": 9})
        if StrategyPrimitive.BOLLINGER_REVERSION in components:
            params.update(
                {
                    "bollinger_period": rng.choice((14, 20, 24)),
                    "bollinger_sigma": rng.choice((1.5, 2.0, 2.5)),
                }
            )
        if StrategyPrimitive.KELTNER_BREAKOUT in components:
            params.update(
                {
                    "keltner_period": rng.choice((14, 20, 24)),
                    "keltner_atr_multiple": rng.choice((1.5, 2.0, 2.5)),
                }
            )
        if StrategyPrimitive.SUPERTREND in components:
            params.update(
                {
                    "supertrend_period": rng.choice((7, 10, 14)),
                    "supertrend_multiple": rng.choice((2.0, 2.5, 3.0, 3.5)),
                }
            )
        if StrategyPrimitive.ATR_VOLATILITY in components or ExitPrimitive.ATR_STOP in exits:
            params.update(
                {
                    "atr_period": rng.choice((7, 14, 21)),
                    "atr_stop_multiple": rng.choice((1.0, 1.5, 2.0, 2.5, 3.0)),
                }
            )
        if StrategyPrimitive.RELATIVE_VOLUME in components:
            params["relative_volume_min"] = rng.choice((1.0, 1.2, 1.5, 2.0))
        if StrategyPrimitive.LIQUIDITY_SWEEP in components or StrategyPrimitive.BOS_CHOCH in components:
            params["structure_lookback"] = rng.choice((5, 8, 13, 21, 34))
        if StrategyPrimitive.FAIR_VALUE_GAP in components:
            params["fvg_min_atr_fraction"] = rng.choice((0.1, 0.2, 0.3, 0.5))
        if StrategyPrimitive.FORECAST_ENSEMBLE in components:
            params["max_forecast_disagreement"] = rng.choice((0.15, 0.25, 0.35, 0.45))
        if StrategyPrimitive.OPTIONS_IV_SKEW in components:
            params["iv_skew_threshold"] = rng.choice((0.02, 0.05, 0.08, 0.12))
        if ExitPrimitive.RISK_REWARD_TARGET in exits:
            params["reward_risk_multiple"] = rng.choice((1.0, 1.25, 1.5, 2.0, 2.5, 3.0))
        if ExitPrimitive.ATR_TRAILING in exits:
            params["trailing_atr_multiple"] = rng.choice((1.0, 1.5, 2.0, 2.5))
        if ExitPrimitive.TIME_STOP in exits:
            params["max_holding_bars"] = rng.choice((3, 5, 8, 13, 21, 34))
        return params


def _stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)
