# AURA AI OS

AURA AI OS is a broker-agnostic, multi-market trading operating system built around one non-negotiable rule: **research, backtest, paper/live execution, portfolio accounting, and risk must share the same core decision path**.

This repository is the production foundation, not a signal-only demo bot.

## Core principles

- Broker-agnostic interfaces and universal domain models.
- Closed-candle decisions by default; no repainting signal path.
- Independent risk engine sits above strategy decisions.
- Same strategy/risk/execution pipeline is reused by backtest and live runtimes.
- Deterministic order state machine with idempotent fills and overfill guards.
- Portfolio ledger tracks cash, average price, realized/unrealized P&L and fees.
- Structured JSON logging for observability and replayability.
- Research must graduate through backtest -> walk-forward/statistical validation -> paper trading before live deployment.
- No AI agent is allowed to mutate a live strategy directly.

## Current foundation

The first implementation includes:

- typed market/order/portfolio domain models
- normalized candle validation
- asynchronous Kraken public candle stream adapter
- deterministic EMA crossover reference strategy for plumbing tests only
- independent portfolio/risk gate with kill switch, daily-loss, drawdown and exposure limits
- order lifecycle state machine and idempotent fill handling
- cash/position ledger with long/short flip accounting
- shared decision pipeline used by both backtest and future live broker runners
- event-driven backtest engine
- structured JSON logging
- unit tests and GitHub Actions CI

> The reference EMA strategy exists only to validate the platform plumbing. It is **not** presented as an alpha strategy and must not be promoted to live trading without the AURA research-validation pipeline.

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
Market data
   |
   v
Normalizer --> Closed Candle --> Strategy --> Signal
                                      |
                                      v
                               Independent Risk Gate
                                      |
                          reject <----+----> approve
                                                   |
                                                   v
                                           Order State Machine
                                                   |
                                                   v
                                               Fill(s)
                                                   |
                                                   v
                                            Portfolio Ledger

Backtest runtime and live runtime call the same DecisionPipeline.
```

## Safety status

AURA is currently in **engineering / research mode**. No live broker execution is enabled in this foundation. Live adapters must be added behind the broker abstraction and must remain gated by paper-trading validation, explicit deployment approval, circuit breakers, and portfolio risk controls.
