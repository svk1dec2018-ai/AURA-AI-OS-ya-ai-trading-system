# AURA AI OS

AURA AI OS is a broker-agnostic, multi-market trading operating system built around one non-negotiable rule: **research, backtest, paper/live execution, portfolio accounting, and risk must share the same core decision path**.

This repository is the production foundation for AURA, not a signal-only demo bot.

## Core principles

- Broker-agnostic interfaces and canonical instrument/symbol mapping.
- Closed-candle decisions by default; no repainting signal path.
- Independent, position-aware risk engine sits above strategy decisions.
- Risk-reducing/flattening orders are distinguished from orders that add exposure.
- Same strategy/risk/execution pipeline is reused by backtest and future live runtimes.
- Deterministic order state machine with idempotent fills, partial-fill VWAP and overfill guards.
- Portfolio ledger tracks cash, average price, realized/unrealized P&L, exposure and fees.
- Structured JSON logging for observability and replayability.
- Research must graduate through backtest -> walk-forward + Monte Carlo -> paper trading -> explicit human approval.
- AI automation may research and attach evidence, but cannot perform final live-strategy approval or replace code under an approved strategy version.

## Implemented foundation

### Domain and market abstraction

- typed market, order, fill and portfolio models
- normalized candle validation with timezone-aware timestamps
- broker-neutral `Instrument` model for equities, indices, futures, options, FX, crypto and commodities
- bidirectional venue symbol mapper with collision protection
- asynchronous Kraken Spot WebSocket v2 OHLC adapter with closed-candle emission semantics

### Strategy and decision path

- closed-candle `Strategy` interface
- deterministic EMA crossover reference strategy for plumbing tests only
- shared `DecisionPipeline` used by backtest and intended live runtimes
- current-position context passed into the independent risk gate

### Independent risk and portfolio accounting

- manual/system kill switch
- maximum order notional, gross exposure, daily-loss and drawdown gates
- position-aware distinction between reductions, closes and new exposure
- flattening remains available when protective risk gates block new risk
- short-opening policy can clip a crossing order to the safe closing quantity
- cash ledger, fees, long/short average cost, realized/unrealized P&L and position flips

### Execution and backtesting

- broker abstraction contract; strategy code does not call broker SDKs directly
- deterministic order state machine
- idempotent fill handling and overfill rejection
- event-driven single-series backtester using the shared decision pipeline
- signal generated on a closed candle and market fill simulated at the next candle open to avoid same-close lookahead execution
- explicit rejection of unsupported multi-symbol input instead of silently producing incorrect portfolio marks

### Strategy research governance

- immutable strategy version identity backed by a content hash
- evidence types for backtest, walk-forward, Monte Carlo and paper trading
- enforced lifecycle promotion rules
- final `PAPER_VALIDATED -> APPROVED` transition requires a human actor
- approved/rejected/retired strategy evidence is immutable
- live deployment gate accepts only `APPROVED` strategy versions

### Quality controls

- structured JSON logging
- pytest regression suite covering order state, portfolio math, backtesting, risk controls, instrument mapping and strategy governance
- GitHub Actions CI on Python 3.11 and 3.12 with Ruff + pytest

> The reference EMA strategy exists only to validate platform plumbing. It is **not** presented as an alpha strategy and must not be promoted to live trading without passing the AURA research-validation lifecycle.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
pytest
python examples/run_backtest.py
```

## Architecture

```text
Venue feeds
    |
    v
Normalizer + Canonical Symbol Mapping
    |
    v
Closed Candle/Event
    |
    v
Strategy / future specialist intelligence
    |
    v
Shared DecisionPipeline
    |
    v
Independent Position-Aware Risk Engine
    |                       |
 reject/clip            approve
                            |
                            v
                    Order State Machine
                            |
                            v
                         Fill(s)
                            |
                            v
                     Portfolio Ledger

Research candidates
    |
    v
Backtest -> Walk-forward + Monte Carlo -> Paper -> Human Approval
                                                    |
                                                    v
                                          Eligible for live loading
```

Backtest and future live runtimes must call the same core strategy/risk decision path. Live broker adapters remain outside strategy code.

See `docs/ARCHITECTURE.md` for system boundaries and `docs/ROADMAP.md` for the implementation sequence.

## Current safety/deployment status

AURA is in **engineering / research mode**. No live-money broker execution is enabled by this foundation. The next execution integrations must remain behind the broker abstraction and must include reconciliation, persistence/WAL, paper-trading validation, deployment approval, circuit breakers, secrets isolation and operational observability before any live-money deployment is considered.
