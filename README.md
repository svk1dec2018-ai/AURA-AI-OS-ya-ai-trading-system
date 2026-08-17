# AURA AI OS

AURA AI OS is a broker-agnostic, multi-market AI trading operating system built around one non-negotiable rule: **research, backtest, paper/live execution, portfolio accounting, intelligence and risk must converge into one governed financial decision path**.

This repository is the production foundation for AURA, not a signal-only demo bot.

## Core principles

- Broker-agnostic interfaces and canonical instrument/symbol mapping.
- Closed-candle decisions by default; no repainting signal path.
- Independent, position-aware risk engine sits above every strategy/model/agent decision.
- Risk-reducing/flattening orders are distinguished from orders that add exposure.
- Same signal -> risk -> order pipeline is reused by conventional strategies and multi-agent CEO decisions.
- Deterministic order state machine with idempotent fills, partial-fill VWAP and overfill guards.
- Portfolio ledger tracks cash, average price, realized/unrealized P&L, exposure and fees.
- Durable append-only financial WAL enables deterministic restart recovery.
- Broker/local reconciliation freezes new risk on critical state divergence rather than silently repairing it.
- Research must graduate through backtest -> walk-forward + Monte Carlo -> paper trading -> explicit human approval.
- AI automation may research, debate and attach evidence, but cannot perform final live-strategy approval or replace code under an approved strategy version.
- Multiple specialist AI agents/providers may work concurrently; the CEO layer synthesizes evidence but does not execute.

## Implemented foundation

### Domain and market abstraction

- typed market, order, fill and portfolio models
- normalized candle validation with timezone-aware timestamps
- broker-neutral `Instrument` model for equities, indices, futures, options, FX, crypto and commodities
- bidirectional venue symbol mapper with collision protection
- asynchronous Kraken Spot WebSocket v2 OHLC adapter with closed-candle emission semantics

### Shared strategy/agent decision path

- closed-candle `Strategy` interface
- deterministic EMA crossover reference strategy for plumbing tests only
- shared `DecisionPipeline.evaluate_signal(...)` used by ordinary strategies and multi-agent CEO candidates
- current-position context passed into the independent risk gate
- no separate permissive AI order path

### Multi-agent intelligence foundation

- concurrent specialist orchestration with per-agent timeout/failure isolation
- specialist roles for HTF bias, SMC/ICT, technical, volume/VWAP, options/volatility, macro/sentiment, cross-market, regime and execution-quality evidence
- typed evidence with source, trust score and point-in-time safety requirements
- deterministic CEO aggregator with quorum/disagreement handling
- provider-agnostic `ReasoningProvider` interface so different models/providers can participate in the same round
- provider/model identity preserved in evidence metadata
- multi-agent decision service routes CEO candidates through the same independent RiskEngine used by normal strategies
- kill switch and risk sizing cannot be overridden by AI consensus

See `docs/MULTI_AGENT_CONSTITUTION.md` for the permanent authority boundaries and target AURA concept.

### Independent risk and portfolio accounting

- manual/system kill switch
- maximum order notional, gross exposure, daily-loss and drawdown gates
- position-aware distinction between reductions, closes and new exposure
- flattening remains available when protective risk gates block new risk
- short-opening policy can clip a crossing order to the safe closing quantity
- cash ledger, fees, long/short average cost, realized/unrealized P&L and position flips

### Durable persistence and recovery

- append-only JSONL write-ahead log with monotonic sequence numbers
- event IDs and correlation IDs
- per-record SHA-256 checksum validation
- truncated/corrupt WAL detection
- typed financial journal for orders, fills and kill-switch transitions
- deterministic restart replay rebuilding order states and portfolio ledger
- duplicate fill replay remains idempotent and cannot double P&L

### Reconciliation

- broker order/position snapshot domain models
- local open-order vs broker open-order comparison
- status and filled-quantity mismatch detection
- broker/local position quantity mismatch detection
- critical divergence produces an explicit `should_freeze_new_orders` signal
- reconciliation intentionally reports/freeze state rather than silently mutating financial truth

### Paper execution

- deterministic broker-agnostic `PaperBroker`
- idempotent client-order submission
- market, limit and stop order simulation
- configurable fees and adverse slippage
- broker-side open-order and position snapshots for reconciliation tests
- cancellation support
- paper fills use the same normalized `Fill` model consumed by AURA accounting

### Execution and backtesting

- broker abstraction contract; strategy/agent code does not call broker SDKs directly
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
- pytest regression coverage for order state, portfolio math, backtesting, risk controls, instruments, governance, WAL integrity, restart recovery, reconciliation, multi-agent orchestration and paper execution
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
Venue feeds / point-in-time research evidence
                |
                v
      Normalizer + Symbol Mapping
                |
                v
        Closed Market Context
                |
       +--------+-----------------------------+
       |                                      |
       v                                      v
 Rules / ML strategy              Concurrent specialist agents
                                          |
                 HTF | SMC | Technical | Volume | Options | Macro | Cross-market | Regime
                                          |
                                          v
                                    CEO Decision Memo
                                          |
                         +----------------+----------------+
                         |                                 |
                         +---------- StrategySignal -------+
                                          |
                                          v
                                Shared DecisionPipeline
                                          |
                                          v
                         Independent Position-Aware Risk Engine
                                  |                  |
                              reject/clip         approve
                                                     |
                                                     v
                                             Order State Machine
                                                     |
                                             Broker / Paper Adapter
                                                     |
                                                     v
                                                  Fill(s)
                                                     |
                                                     v
                                              Portfolio Ledger
                                                     |
                                                     v
                                               WAL / Audit Trail

Restart: WAL -> deterministic recovery -> broker reconciliation
                                      |
                              mismatch -> freeze new risk

Research candidates:
Research -> Backtest -> Walk-forward + Monte Carlo -> Paper -> Human Approval
                                                         |
                                                         v
                                               Eligible for controlled loading
```

## Current safety/deployment status

AURA remains in **engineering / research + deterministic paper foundation mode**. A live-money broker adapter is intentionally not enabled yet. Before controlled live deployment, the system still needs broader data-quality gates, multi-asset portfolio mechanics, richer execution/reconciliation supervision, research-grade multi-symbol backtesting, extended paper operation, secrets isolation, observability/alerts, connector-specific sandbox validation and governance-approved strategy evidence.

See:

- `docs/MULTI_AGENT_CONSTITUTION.md` — permanent AI/authority contract
- `docs/ARCHITECTURE.md` — system boundaries/invariants
- `docs/ROADMAP.md` — dependency-ordered implementation plan
- `SECURITY.md` — financial-system security boundaries
