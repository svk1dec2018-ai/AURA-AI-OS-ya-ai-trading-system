# AURA AI OS Implementation Roadmap

This roadmap is ordered by financial safety and dependency, not by visual appeal. Later intelligence must not bypass unfinished financial infrastructure.

## Phase 0 — Foundation: implemented

- canonical market/order/fill/portfolio models
- timezone-aware normalized candles
- broker-neutral instrument identity and venue symbol mapping
- closed-candle strategy interface
- shared strategy/agent signal -> risk -> order decision pipeline
- position-aware independent risk gate
- order state machine, idempotent fills and overfill protection
- cash/position/P&L ledger
- event-driven single-series backtest engine
- public Kraken closed-candle feed adapter
- structured JSON logging
- strategy validation/promotion firewall
- Python 3.11/3.12 CI with lint and regression tests

## Phase 1 — Durable execution foundation: substantially implemented

Implemented:

- append-only write-ahead log for order/fill/risk lifecycle
- event IDs, correlation IDs, sequence validation and checksums
- truncated/corrupt WAL detection
- deterministic restart replay
- order/client-order identity preservation
- duplicate-fill-safe state restoration
- broker order/position reconciliation comparison
- explicit freeze-new-risk signal for critical broker/local divergence
- deterministic paper broker adapter
- market/limit/stop paper execution with costs/slippage
- broker-side paper order/position snapshots
- idempotent paper order submission

Still required before Phase 1 is considered fully closed:

- durable checkpoint/snapshot compaction while preserving WAL auditability
- connector health state and circuit breakers
- standardized timeout/retry/idempotency policy around network brokers
- reconciliation of broker cash/balances and complete historical fill sets
- disconnect/reconnect/fault-injection supervisor tests
- operational recovery runbook

Exit criteria:
- process can crash/restart without duplicating fills or losing financial state
- reconciliation identifies and surfaces broker/local mismatches
- paper execution survives disconnect/reconnect and fault-injection scenarios

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
- walk-forward runner with explicit label-horizon purge
- bootstrap/Monte Carlo robustness analysis
- parameter stability analysis
- regime-segmented performance
- reproducible experiment manifests and hashes

Exit criteria:
- every promoted strategy has reproducible source data, configuration, code hash and validation artifacts

## Phase 4 — Market intelligence/evidence engine: interfaces started

Implemented foundation:

- typed specialist roles
- typed evidence with confidence, risk flags and source metadata
- point-in-time-safe evidence validation
- provider/model identity plumbing

Still required:

- higher-timeframe trend/bias feature producer
- validated market structure / SMC/ICT feature producer
- technical momentum/mean-reversion feature producer
- VWAP/volume/volume-profile producer
- options/volatility/Greeks evidence producer
- cross-market/intermarket producer
- macro calendar/economic-event producer
- source-backed news/sentiment producer
- regime/chop/OOD/drift producer
- execution-quality/spread/liquidity producer
- evidence freshness/staleness and contradiction gates
- RAG/knowledge firewall integration

Rules:
- features must be causal and timestamped
- future information/leakage is forbidden
- every evidence item carries source, freshness and confidence metadata
- missing evidence is explicit; it is not silently fabricated

## Phase 5 — Multi-agent research and CEO decision layer: orchestration foundation implemented

Implemented:

- concurrent specialist execution
- per-agent timeout and failure isolation
- multiple provider/model support through a common `ReasoningProvider` contract
- deterministic CEO evidence aggregation
- quorum and disagreement handling
- supporting/opposing/abstaining agent audit trail
- CEO output converted to a normal `StrategySignal`
- multi-agent output routed through the same independent RiskEngine as conventional strategies
- kill switch/risk sizing proven to remain authoritative over CEO output
- permanent authority contract in `docs/MULTI_AGENT_CONSTITUTION.md`

Still required:

- concrete specialist feature implementations
- production LLM/model provider adapters with secrets isolation
- forced knowledge/RAG check before applicable research/macro claims
- contradiction detection and trust weighting
- model/version/prompt manifest persistence
- CEO evidence-round persistence in audit WAL/event store
- research agent strategy/hypothesis generation workflow
- agent evaluation, calibration and drift monitoring

Non-negotiable:
- agents cannot approve a strategy for live deployment
- agents cannot mutate deployed strategy code
- agents cannot call broker execution directly
- independent risk is not a voting agent

Exit criteria:
- every AI-generated decision is explainable through persisted evidence and model/strategy versions

## Phase 6 — Live paper runtime and observability

- 24x7 supervisor
- live market scanners by asset class/timeframe
- multi-agent round scheduling across symbols/timeframes
- deterministic paper execution wired end-to-end to the WAL/recovery/reconciliation stack
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

- Indian equity/futures/options brokers such as Dhan/Shoonya where account/API access supports the required functions
- Binance-compatible crypto trading
- Kraken crypto
- MT5/FX connector where legally/account-wise appropriate
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

Do not optimize for a claimed win rate, trade frequency or profit target before the data, execution and validation layers can measure them realistically. AURA should scan broadly and avoid an artificial "never trade" bias, but it must not force trades to satisfy a quota. Alpha claims come only from validated out-of-sample results with realistic costs, execution and failure modes.
