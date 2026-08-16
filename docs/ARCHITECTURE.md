# AURA AI OS Architecture

## 1. Architectural invariants

These rules are intentionally harder to change than individual strategies or connectors.

1. **One decision path.** Backtest, paper and live runtimes must call the same strategy -> risk -> execution-intent pipeline. Runtime-specific code may provide data or execute approved orders, but may not fork strategy logic.
2. **Risk is independent.** Strategy, AI and research components propose intent. The risk layer determines whether new exposure is allowed and may reject or resize it.
3. **Exits remain possible.** Protective gates must distinguish risk reduction from risk creation so that drawdown or kill-switch states do not accidentally trap a position.
4. **Closed-candle causality.** Candle strategies receive closed bars. Backtests cannot execute a signal at a price that was not available after the signal existed.
5. **Canonical instruments.** Strategy and portfolio layers operate on broker-neutral identities. Venue-specific symbols live at connector boundaries.
6. **Idempotent financial events.** Duplicate fills must not change cash, position or P&L twice.
7. **Immutable strategy versions.** A version identity cannot silently point to different code.
8. **AI cannot self-promote to live.** Automated research may create candidates and evidence; final live approval requires an explicit human actor.
9. **Secrets do not enter strategy code.** API keys and credentials belong only in deployment/connector configuration.
10. **Live money is not a development environment.** Research must graduate through validation and paper execution before live deployment.

## 2. Layers

### Domain

`aura/domain/`

Owns canonical models and identities. It must not import broker SDKs or strategy implementations.

Current responsibilities:
- candles, signals, orders, fills and portfolio snapshots
- canonical instruments and asset classes
- venue symbol mapping

### Data

`aura/data/`

Owns venue ingestion and normalization. Adapters translate external schemas into AURA domain events.

Current implementation:
- canonical candle normalizer
- Kraken Spot WebSocket v2 OHLC adapter

Planned:
- historical data adapters
- data quality/gap detection
- exchange/broker adapters for additional markets
- durable raw/normalized event storage
- clock, sequence and stale-data guards

### Strategy

`aura/strategy/`

Produces trade intent from causal market history. Strategy code does not know broker credentials or send orders.

The existing EMA strategy is a deterministic integration fixture, not production alpha.

Planned specialist evidence modules can include technical/market-structure, volume/VWAP, volatility/options, macro/news and cross-market evidence, but all must return structured evidence into a controlled decision layer.

### Core decision pipeline

`aura/core/`

The shared path between strategy and risk. A runtime supplies closed market history, portfolio state and position state; the pipeline produces either no action, a rejection/clip or an approved order intent.

This interface is the primary protection against backtest/live logic drift.

### Risk

`aura/risk/`

Independent pre-trade portfolio protection.

Implemented:
- kill switch
- daily-loss and drawdown gates
- order-notional and gross-exposure caps
- short-opening policy
- position-aware reduction/close handling

Planned:
- per-instrument and sector limits
- concentration limits
- volatility-scaled sizing
- VaR/CVaR and stress scenarios
- correlation/beta limits
- liquidity/slippage gates
- stale-data and venue-health circuit breakers
- portfolio-level open-risk accounting

### Execution

`aura/execution/`

Owns order lifecycle and broker translation.

Implemented:
- broker adapter contract
- deterministic state transitions
- partial fills and VWAP
- fill idempotency and overfill protection

Planned before live execution:
- durable write-ahead log/event store
- broker order-id mapping
- restart recovery
- open-order/position/cash reconciliation
- retry policy with idempotency keys
- rate-limit and circuit-breaker handling
- paper broker adapter
- live adapters only after paper validation

### Portfolio

`aura/portfolio/`

Owns cash and inventory accounting.

Implemented:
- signed long/short positions
- average-cost basis
- realized/unrealized P&L
- fees
- long/short flips
- gross/net exposure
- peak equity and drawdown

Planned:
- multi-currency cash
- contract multipliers
- futures variation margin
- options Greeks and assignment/exercise lifecycle
- corporate actions
- portfolio attribution

### Research governance

`aura/research/`

Separates strategy invention from deployment authority.

Current lifecycle:

```text
RESEARCH
  -> BACKTEST_VALIDATED
  -> ROBUSTNESS_VALIDATED      # walk-forward + Monte Carlo evidence
  -> PAPER_VALIDATED
  -> APPROVED                  # human actor only
  -> RETIRED
```

A strategy may be rejected before approval. Approved/rejected/retired versions are terminal for evidence mutation; new code requires a new version/hash.

## 3. Runtime separation

### Backtest runtime

- replays normalized historical events
- calls the shared decision pipeline
- simulates fills after a signal becomes knowable
- uses the same ledger/risk abstractions

The current backtester is deliberately single-series. It rejects multi-symbol input instead of pretending that incomplete marks constitute a portfolio backtest.

### Paper runtime — next target

- consumes live normalized market events
- calls the same decision pipeline
- executes through a deterministic simulated broker
- persists orders/fills/state
- supports reconciliation and restart

### Live runtime — later gated target

- may load only a governance-approved strategy version
- must use a broker adapter and independent risk layer
- must persist and reconcile state
- must expose operational kill switches and health telemetry
- must not allow an LLM/agent to edit running strategy code

## 4. Future intelligence layer

AURA's future multi-agent intelligence should sit **upstream of the risk engine** and operate as evidence producers, not privileged executors.

Suggested roles:
- market/regime scout
- higher-timeframe bias specialist
- market-structure/SMC specialist
- volume/VWAP/order-flow specialist
- volatility/options specialist
- macro/news/sentiment specialist
- cross-market confirmation specialist
- research/evolution agent
- CEO/decision aggregator

The CEO layer may aggregate structured evidence into strategy intent, but the independent risk engine remains authoritative for exposure and the governance layer remains authoritative for deployment.

## 5. Persistence target

AURA should evolve toward event-sourced recovery:

```text
market event -> decision -> risk decision -> order intent -> broker ack -> fill
                                                      |             |
                                                      +---- WAL ----+
                                                               |
                                                               v
                                                        reconciliation
                                                               |
                                                               v
                                                         portfolio state
```

Critical financial state must be reproducible from persisted events plus controlled snapshots.

## 6. Definition of "live-ready"

A feature being implemented is not the same as the platform being live-ready. Before live-money execution, at minimum the repository must have:

- durable state/WAL and crash recovery
- broker reconciliation
- paper broker and prolonged paper validation
- realistic fees/slippage/latency handling
- portfolio-level risk and stress controls
- secrets management
- monitoring/alerts/audit trail
- deployment versioning and rollback
- approved strategy artifact binding
- connector-specific integration tests
- operational runbooks and failure drills

Until these exist and are validated, AURA remains an engineering/research system.
