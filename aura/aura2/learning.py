from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StrategyKey:
    symbol: str
    strategy: str
    regime: str
    session: str

    def storage_key(self) -> str:
        return "|".join(
            part.strip().upper() for part in (
                self.symbol,
                self.strategy,
                self.regime,
                self.session,
            )
        )


@dataclass(slots=True)
class StrategyStats:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_win_r: float = 0.0
    gross_loss_r: float = 0.0
    ewma_quality: float = 0.0

    def update(self, *, return_r: float, max_adverse_r: float = 0.0, alpha: float = 0.08) -> None:
        reward = max(-3.0, min(3.0, float(return_r)))
        adverse_penalty = min(1.0, max(0.0, float(max_adverse_r))) * 0.25
        quality = reward - adverse_penalty
        self.ewma_quality = alpha * quality + (1.0 - alpha) * self.ewma_quality
        self.trades += 1
        if return_r > 0:
            self.wins += 1
            self.gross_win_r += float(return_r)
        elif return_r < 0:
            self.losses += 1
            self.gross_loss_r += abs(float(return_r))

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss_r == 0:
            return self.gross_win_r if self.gross_win_r else 0.0
        return self.gross_win_r / self.gross_loss_r

    @property
    def weight(self) -> float:
        # Deliberately bounded: learning may rank strategies, never create leverage.
        sample_confidence = min(1.0, self.trades / 100.0)
        edge = self.ewma_quality * 0.30
        edge += (self.win_rate - 0.50) * 0.40 * sample_confidence
        if self.profit_factor > 0:
            edge += max(-0.25, min(0.25, (self.profit_factor - 1.0) * 0.10))
        return max(0.50, min(1.75, 1.0 + edge))


class PerformanceMemory:
    """Restart-safe online strategy ranking.

    This memory cannot change risk-per-trade, drawdown limits, broker permissions,
    position limits, or any other financial authority.
    """

    def __init__(self) -> None:
        self._stats: dict[str, StrategyStats] = {}

    def update(
        self,
        key: StrategyKey,
        *,
        return_r: float,
        max_adverse_r: float = 0.0,
    ) -> StrategyStats:
        stats = self._stats.setdefault(key.storage_key(), StrategyStats())
        stats.update(return_r=return_r, max_adverse_r=max_adverse_r)
        return stats

    def get(self, key: StrategyKey) -> StrategyStats:
        return self._stats.get(key.storage_key(), StrategyStats())

    def rank(self, keys: list[StrategyKey]) -> list[tuple[StrategyKey, StrategyStats]]:
        ranked = [(key, self.get(key)) for key in keys]
        return sorted(ranked, key=lambda item: item[1].weight, reverse=True)

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: asdict(stats) for key, stats in sorted(self._stats.items())}
        destination.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> PerformanceMemory:
        memory = cls()
        source = Path(path)
        if not source.exists():
            return memory
        payload = json.loads(source.read_text(encoding="utf-8"))
        memory._stats = {key: StrategyStats(**value) for key, value in payload.items()}
        return memory
