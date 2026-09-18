import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.agents.models import AgentContext
from aura.aura2.scanner_bridge import AURA2MTFScanner
from aura.aura2.specialist import AURA2MTFSpecialist
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.strategy.features import FeatureSnapshot


class FakeFeatureEngine:
    def compute(self, candles, *, decision_time=None):
        timeframe = candles[-1].timeframe
        bullish = timeframe in {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
        return _snapshot(timeframe, bullish=bullish)


class CapturingScanner:
    def __init__(self) -> None:
        self.contexts = ()

    async def scan(self, contexts):
        self.contexts = tuple(contexts)
        return self.contexts


def _snapshot(timeframe: str, *, bullish: bool) -> FeatureSnapshot:
    if bullish:
        ema21, ema50, ema200 = Decimal(101), Decimal(100), Decimal(99)
        rsi, macd, vwap, supertrend = Decimal(60), Decimal(1), Decimal(100), 1
    else:
        ema21, ema50, ema200 = Decimal(99), Decimal(100), Decimal(101)
        rsi, macd, vwap, supertrend = Decimal(40), Decimal(-1), Decimal(102), -1
    return FeatureSnapshot(
        symbol="XAUUSD",
        venue="MT5",
        timeframe=timeframe,
        as_of=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
        bars_used=250,
        close=Decimal(101),
        ema_8=None,
        ema_21=ema21,
        ema_50=ema50,
        ema_200=ema200,
        rsi_14=rsi,
        macd_line=None,
        macd_signal=None,
        macd_histogram=macd,
        bollinger_mid=None,
        bollinger_upper=None,
        bollinger_lower=None,
        atr_14=Decimal("0.5"),
        supertrend=Decimal(100),
        supertrend_direction=supertrend,
        vwap=vwap,
        obv=Decimal(0),
        vpt=Decimal(0),
        support=None,
        resistance=None,
    )


def _context(timeframe: str, minute: int) -> AgentContext:
    close_time = datetime(2026, 9, 18, 12, minute, tzinfo=UTC)
    candle = NormalizedCandle(
        symbol="XAUUSD",
        venue="MT5",
        timeframe=timeframe,
        open_time=close_time - timedelta(minutes=1),
        close_time=close_time,
        open=Decimal(100),
        high=Decimal(102),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(10),
        closed=True,
    )
    return AgentContext(
        correlation_id=f"xau:{timeframe}:{minute}",
        symbol="XAUUSD",
        decision_timeframe=timeframe,
        candles=(candle,),
        created_at=close_time,
    )


def test_aura2_scanner_caches_cross_timeframe_state() -> None:
    inner = CapturingScanner()
    scanner = AURA2MTFScanner(inner, feature_engine=FakeFeatureEngine())

    asyncio.run(scanner.scan([_context("1m", 1)]))
    first = inner.contexts[0].metadata["aura2_mtf"]
    assert first["timeframes"] == ["M1"]

    asyncio.run(scanner.scan([_context("1h", 2)]))
    second = inner.contexts[0].metadata["aura2_mtf"]
    assert second["timeframes"] == ["M1", "H1"]
    assert second["direction"] == "BUY"
    assert second["execution_authority"] is False
    assert scanner.status()["cached_frames"] == 2


def test_aura2_mtf_specialist_is_advisory_only() -> None:
    context = _context("1m", 3)
    context = context.model_copy(
        update={
            "metadata": {
                "aura2_mtf": {
                    "direction": "BUY",
                    "confidence": 0.90,
                    "agreement": 0.85,
                    "execution_alignment": 1.0,
                    "higher_timeframe_alignment": 0.80,
                    "regime": "TREND",
                    "timeframes": ["M1", "M5", "M15", "H1", "H4"],
                    "frame_count": 5,
                    "execution_authority": False,
                    "risk_authority": False,
                }
            }
        }
    )
    evidence = asyncio.run(AURA2MTFSpecialist().analyze(context))
    assert evidence.intent == SignalIntent.LONG
    assert evidence.confidence > 0.70
    assert evidence.execution_authority is False
    assert evidence.features["aura2_mtf"]["risk_authority"] is False
