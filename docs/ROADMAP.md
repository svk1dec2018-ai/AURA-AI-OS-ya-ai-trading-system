# AURA AI OS Implementation Roadmap

This roadmap is ordered by financial safety and dependency, not by visual appeal. Later intelligence must not bypass unfinished financial infrastructure.

## Phase 0 — Foundation: implemented

- canonical market/order/fill/portfolio models
- timezone-aware normalized candles
- broker-neutral instrument identity and venue symbol mapping
- closed-candle strategy interface
- shared strategy -> risk -> order decision pipeline
- position-aware independent risk gate
- order state machine, idempotent fills and overfill protection
- cash/position/P&L ledger
- event-driven single-series backtest engine
- public Kraken closed-candle feed adapter
- structured JSON logging
- strategy validation/promotion firewall
- Python 3.11/3.12 CI with lint and regression tests

## Phase 1 — Durable execution foundation

Priority: highest.

- append-only write-ahead log for order/fill lifecycle
- event IDs, correlation IDs and replay
- durable portfolio snapshots
- broker order-id/client-order-id mapping
- restart recovery
- reconciliation service for cash, positions, open orders and fills
- timeout/retry/idempotency policy
- connector health state and circuit breakers
- deterministic paper broker adapter
- failure-injection tests

Exit criteria:
- process can crash/restart without duplicating fills or losing financial state
- reconciliation identifies and surfaces broker/local mismatches
- paper execution survives disconnect/reconnect scenarios

## Phase 2 — Portfolio and institutional risk expansion

- instrument multipliers/tick sizes/lot sizes
- multi-currency cash ledger
- futures margin and mark-to-market mechanics
- options contract metadata and Greeks plumbing
- per-symbol/asset-class/sector exposure limits
- concentration and correlation limits
- volatility-based sizing
- VaR/CVaR and stress scenarios
- drawdown and loss-budget hierarchy
- liquidity/slippage/spread filters
- portfolio-level kill switches
- stale-price/data-quality gates

Exit criteria:
- risk is evaluated at order, strategy, instrument and portfolio levels
- reducing/flattening behavior is tested under every protective gate

## Phase 3 — Research-grade backtesting

- multi-symbol event scheduler
- historical data adapters and source provenance
- corporate-action aware equities handling
- futures rolls and expiries
- options chain replay where reliable data is available
- transaction costs, spread, slippage and latency models
- market-session/calendar handling
- limit/stop/partial-fill simulation
- walk-forward runner
- bootstrap/Monte Carlo robustness analysis
- parameter stability analysis
- regime-segmented performance
- reproducible experiment manifests and hashes

Exit criteria:
- every promoted strategy has reproducible source data, configuration, code hash and validation artifacts

## Phase 4 — Market intelligence/evidence engine

Add specialist evidence producers behind stable typed interfaces:

- higher-timeframe trend/bias
- technical momentum/mean-reversion evidence
- market structure / SMC-style structural features
- VWAP, volume and volume-profile evidence
- volatility and options evidence
- cross-market/intermarket evidence
- macro calendar and economic-event evidence
- news/sentiment evidence with source/time provenance
- market regime/chop detection

Rules:
- features must be causal and timestamped
- future information/leakage is forbidden
- every evidence item carries source, freshness and confidence metadata
- missing evidence is explicit; it is not silently fabricated

## Phase 5 — Multi-agent research and CEO decision layer

- specialist agents consume structured evidence, not raw unrestricted broker control
- CEO layer aggregates independent specialist outputs
- disagreement and uncertainty are preserved
- research agent can propose hypotheses and new strategy versions
- RAG/source firewall for external research
- contradiction detection and trust weighting
- all generated strategy candidates enter `RESEARCH` stage
- agents cannot approve a strategy for live deployment
- agents cannot mutate deployed strategy code

Exit criteria:
- every AI-generated decision is explainable through persisted evidence and model/strategy versions

## Phase 6 — Live paper runtime and observability

- 24x7 supervisor
- live market scanners by asset class/timeframe
- deterministic paper execution
- dashboard/API for positions, exposure, P&L and system health
- alerts for risk, stale data, broker disconnects, reconciliation mismatches and strategy state
- audit journal and decision explanations
- controlled Telegram/other notification adapters
- deployment manifests and rollback

Exit criteria:
- extended paper operation with no unresolved state/reconciliation defects
- operational incidents are detectable and recoverable

## Phase 7 — Broker/venue integrations

Implement one connector at a time behind common interfaces. Candidate families:

- Indian equity/futures/options brokers
- Binance-compatible crypto trading
- Kraken crypto
- FX/CFD connector where legally/account-wise appropriate
- commodities through supported broker/exchange APIs

Each connector requires:
- official API schema mapping
- symbol/contract metadata mapping
- order-type capability matrix
- rate-limit behavior
- reconciliation tests
- sandbox/paper verification where available
- secrets kept outside repository

## Phase 8 — Controlled live deployment

Only after the earlier phases satisfy their exit criteria:

- load only governance-approved strategy versions
- smallest-risk deployment first
- hard portfolio caps and daily loss budget
- operational kill switch
- canary rollout
- monitored rollback procedure
- immutable audit trail
- no autonomous production code mutation

## Parallel quality track

Continuous across every phase:

- unit/property/integration tests
- code quality and type checking
- security scanning
- dependency pinning/update policy
- performance profiling
- chaos/failure testing
- documentation and runbooks
- reproducibility manifests
- data/source licensing review

## Non-goals until the foundation supports them

Do not optimize for a claimed win rate, trade frequency or profit target before the data, execution and validation layers can measure them realistically. AURA should optimize for valid evidence, realistic simulation, controlled risk and reproducibility first; alpha claims come only from validated results.
