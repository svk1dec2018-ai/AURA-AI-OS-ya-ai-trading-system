from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import aura.runtime.free_public_ai_council as runtime_module
from aura.agents.models import AgentContext
from aura.domain.models import NormalizedCandle
from aura.runtime.free_public_ai_council import (
    FreePublicAICouncilConfig,
    FreePublicAICouncilRuntime,
)


class _Feed:
    def stop(self) -> None:
        return None


class _HistoryClient:
    supported_timeframes = frozenset({"5m"})

    async def fetch_candles(self, *, symbol, timeframe, limit, end=None):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        return tuple(
            _candle(
                symbol=symbol,
                timeframe=timeframe,
                opened=start + timedelta(minutes=5 * index),
                price=Decimal(100 + index),
            )
            for index in range(limit)
        )


class _FailingHistoryClient:
    supported_timeframes = frozenset({"5m"})

    async def fetch_candles(self, **_kwargs):
        raise RuntimeError("provider unavailable")


class _IntelligenceService:
    def __init__(self) -> None:
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    def metadata_for(self, symbol, *, decision_time, limit):
        return {
            "external_intelligence_events": [
                {
                    "event_id": "news-1",
                    "source": "TEST_OFFICIAL",
                    "kind": "news",
                    "title": f"Point-in-time event for {symbol}",
                    "published_at": decision_time.isoformat(),
                    "observed_at": decision_time.isoformat(),
                    "summary": "",
                    "symbols": [],
                    "topics": [],
                    "trust_score": 1.0,
                }
            ][:limit]
        }

    def status(self):
        return {
            "events_cached": int(self.started),
            "last_poll_at": None,
            "errors": {},
            "gdelt_queries": [],
            "official_india_enabled": False,
        }


def _candle(
    *,
    symbol: str,
    timeframe: str,
    opened: datetime,
    price: Decimal,
) -> NormalizedCandle:
    duration = timedelta(seconds=1) if timeframe == "1s" else timedelta(minutes=5)
    return NormalizedCandle(
        symbol=symbol,
        venue="COINBASE_PUBLIC",
        timeframe=timeframe,
        open_time=opened,
        close_time=opened + duration,
        open=price,
        high=price + Decimal("0.1"),
        low=price - Decimal("0.1"),
        close=price,
        volume=Decimal(10),
    )


def _patch_ai_team(monkeypatch) -> None:
    fake_team = SimpleNamespace(
        agents=(SimpleNamespace(agent_id="ai-council:test"),),
        orchestrator=object(),
        ceo=object(),
        risk_policy=object(),
    )
    monkeypatch.setattr(
        runtime_module,
        "build_default_agent_team",
        lambda *_args, **_kwargs: fake_team,
    )


@pytest.mark.asyncio
async def test_runtime_builds_full_causal_public_context(tmp_path, monkeypatch) -> None:
    _patch_ai_team(monkeypatch)
    intelligence = _IntelligenceService()
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "risk.md").write_text(
        "Trading risk position sizing volatility and regime discipline.",
        encoding="utf-8",
    )
    (corpus / "manifest.jsonl").write_text(
        """{"entry_id":"risk","source_id":"user:risk","source_type":"book","title":"Risk Notes","relative_path":"risk.md","publication_date":"2020-01-01T00:00:00Z","license":"user_provided","confidence":0.8,"trust_score":0.8}\n""",
        encoding="utf-8",
    )
    runtime = FreePublicAICouncilRuntime(
        FreePublicAICouncilConfig(
            symbols=("BTC-USD", "ETH-USD"),
            timeframes=("1s", "5m"),
            decision_timeframe="1s",
            htf_timeframe="5m",
            min_history_bars=30,
            max_history_bars=50,
            history_seed_bars=30,
            knowledge_dir=corpus,
            state_dir=tmp_path,
        ),
        feed=_Feed(),
        history_client=_HistoryClient(),
        intelligence_service=intelligence,
    )

    await runtime._start_context_services()
    assert intelligence.started is True
    assert runtime.history_seed_counts == {"BTC-USD:5m": 30, "ETH-USD:5m": 30}

    opened = datetime.now(UTC) + timedelta(seconds=1)
    btc_history = tuple(
        _candle(
            symbol="BTC-USD",
            timeframe="1s",
            opened=opened + timedelta(seconds=index),
            price=Decimal(200 + index),
        )
        for index in range(30)
    )
    eth_history = tuple(
        _candle(
            symbol="ETH-USD",
            timeframe="1s",
            opened=opened + timedelta(seconds=index),
            price=Decimal(100 + index),
        )
        for index in range(30)
    )
    for candle in (*btc_history, *eth_history):
        runtime._append_history(candle)
    context = AgentContext(
        correlation_id="public-context-1",
        symbol="BTC-USD",
        decision_timeframe="1s",
        candles=btc_history,
        created_at=btc_history[-1].close_time,
    )

    enriched = await runtime._enrich_context(context)

    assert len(enriched.metadata["htf_candles"]) == 30
    assert enriched.metadata["cross_market_observations"][0]["related_symbol"] == "ETH-USD"
    assert enriched.metadata["live_intelligence"][0]["event_id"] == "news-1"
    assert enriched.metadata["retrieved_knowledge"][0]["source_id"] == "user:risk"
    assert enriched.metadata["forecast_ensemble"]["contributing_models"] == (
        "baseline:ema-trend:v1",
        "baseline:rolling-drift:v1",
    )
    assert enriched.metadata["context_coverage"]["forecast_ensemble"] is True
    assert enriched.metadata["context_coverage"]["execution_quality"] is False
    assert enriched.metadata["context_coverage"]["options_snapshot"] is False


@pytest.mark.asyncio
async def test_history_provider_failure_is_visible_and_non_blocking(tmp_path, monkeypatch) -> None:
    _patch_ai_team(monkeypatch)
    runtime = FreePublicAICouncilRuntime(
        FreePublicAICouncilConfig(
            symbols=("BTC-USD",),
            timeframes=("1s", "5m"),
            htf_timeframe="5m",
            min_history_bars=10,
            max_history_bars=20,
            history_seed_bars=10,
            enable_live_intelligence=False,
            state_dir=tmp_path,
        ),
        feed=_Feed(),
        history_client=_FailingHistoryClient(),
        intelligence_service=_IntelligenceService(),
    )

    await runtime._start_context_services()

    assert runtime.history_seed_counts["BTC-USD:5m"] == 0
    assert "provider unavailable" in runtime.history_seed_errors["BTC-USD:5m"]
