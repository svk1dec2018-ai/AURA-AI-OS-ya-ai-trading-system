# AURA AI OS — Current Implementation Status

This file describes what is implemented in code today versus what remains intentionally gated. It complements `MULTI_AGENT_CONSTITUTION.md` and `ROADMAP.md`.

## Implemented and wired

### 1. Shared financial core

- canonical candles, orders, fills and portfolio snapshots
- broker-neutral instrument and venue symbol mapping
- one shared signal -> independent RiskEngine -> order path
- position-aware exposure reduction vs new-risk distinction
- kill switch, max order notional, gross exposure, daily-loss and drawdown controls
- deterministic order state machine
- idempotent fills, partial-fill VWAP and overfill rejection
- cash/position ledger with fees, realized/unrealized P&L and long/short flips

### 2. Durable state and recovery

- checksum-protected append-only JSONL WAL
- monotonic event sequence and event/correlation IDs
- typed financial event journal
- deterministic restart replay
- duplicate-fill-safe recovery
- atomic checksum-protected financial checkpoints
- checkpoint + WAL-tail recovery without deleting the immutable WAL audit trail
- broker/local order and position reconciliation
- reconciliation divergence freezes new risk and never silently self-heals

### 3. Execution resilience and paper broker

- broker abstraction contract
- bounded transient retry primitives
- connector circuit breaker: CLOSED / OPEN / HALF_OPEN
- idempotency-aware retry guard: unsafe order submission gets one attempt unless venue semantics prove safe idempotency
- deterministic PaperBroker
- market, limit and stop simulation
- configurable fee and adverse-slippage assumptions
- broker-side paper order/position snapshots

### 4. Market-data safety

- closed-candle normalization
- duplicate/out-of-order/gap/stale/future-data quality checks
- bad market data can block an intelligence round before agents run
- Kraken public closed-candle WebSocket adapter foundation
- operational feed-freshness supervisor that may engage the financial kill switch

### 5. Nine-role concurrent AURA intelligence team

The default team runs these roles concurrently:

1. HTF Bias
2. SMC/ICT Structure
3. Technical
4. Volume/VWAP
5. Options/Volatility
6. Macro/Sentiment via KnowledgeFirewall
7. Cross-Market
8. Regime
9. Execution Quality

Implemented intelligence infrastructure:

- async concurrent specialist orchestrator
- per-agent timeout and failure isolation
- typed point-in-time AgentEvidence
- source/trust/provenance metadata
- provider-agnostic `ReasoningProvider` interface for adding multiple AI providers/models to the same round
- provider/model identity retained in evidence
- deterministic CEO aggregator with quorum/disagreement/support/opposition/abstention tracking
- complete agent-round + CEO audit persistence to WAL
- AgentRiskPolicy hard-block layer before financial risk
- required-role missing/failure/warmup/unavailable checks
- execution-quality and future-data/knowledge-contradiction hard blocks
- CEO output still passes through the independent financial RiskEngine; AI consensus cannot override it

### 6. Concrete specialist logic

Implemented causal deterministic specialists:

- Technical: EMA + RSI evidence
- SMC/ICT-style structure: causal liquidity sweep/reclaim and displacement features
- Volume/VWAP: VWAP + relative participation
- Regime: trend/chop advisory
- HTF Bias: higher-timeframe EMA context with point-in-time validation
- Options/Volatility: IV/PCR advisory and volatility risk flags; no fabricated direction when reliable directional derivatives evidence is absent
- Cross-Market: weighted trusted related-market observations
- Macro/Sentiment: only trusted structured claims from KnowledgeFirewall
- Execution Quality: spread, estimated slippage and top-of-book liquidity risk flags

### 7. Knowledge / RAG firewall

- trust-score threshold
- publication and observation timestamps
- point-in-time retrieval bundles
- identical-content deduplication
- per-source versioning
- structured claims
- explicit contradiction detection
- contradictory knowledge blocks safe decision use rather than silently choosing one claim

### 8. Paper runtimes

Single-event MultiAgentPaperRuntime:

- rolling per-symbol/timeframe history for specialist warmups
- retained multi-symbol marks for portfolio valuation
- optional metadata-enrichment hook for HTF/options/cross-market/execution inputs
- fills journaled before local ledger mutation
- agent-round audit persistence
- order-created -> broker submit -> order-submitted journaling
- no same-bar signal fill
- reconciliation against PaperBroker state

MultiMarketPaperCoordinator:

- processes same-close-time symbol batches
- advances existing paper orders first
- updates all current marks/history
- scans markets concurrently
- runs full specialist rounds concurrently per context
- centrally serializes portfolio allocation after intelligence
- reserves approved-but-unfilled gross exposure so simultaneous opportunities cannot double-use capital
- submits paper orders only after current batch execution has finished
- one shared RiskEngine authority enforced between coordinator and allocator

### 9. Multi-market scanning and allocation

- concurrent MultiMarketIntelligenceScanner
- deterministic opportunity ranking
- data-quality and AgentRiskPolicy filtering
- PortfolioRiskCoordinator
- approved-but-unfilled exposure reservation
- current-position-aware allocation
- concurrent intelligence / centralized financial authority separation

### 10. Backtesting and research robustness

- single-series event-driven next-bar-open backtester
- causal MultiSymbolEventScheduler
- shared-portfolio MultiSymbolBacktestEngine
- same-time market signals ranked deterministically
- one shared RiskEngine required across all symbols
- approved-but-unfilled historical exposure reserved within each event batch
- leakage-safe rolling and expanding walk-forward splits
- block-bootstrap Monte Carlo with deterministic seeds
- probability-of-loss and drawdown distribution metrics
- robustness threshold decision
- measured walk-forward/Monte-Carlo outputs automatically generate governance evidence; callers cannot manually claim a pass

### 11. Research reproducibility and deployment governance

- immutable StrategyVersion identity/content hash
- backtest / walk-forward / Monte Carlo / paper evidence stages
- final strategy approval requires human actor
- approved/rejected/retired evidence immutability
- live eligibility only for APPROVED versions
- point-in-time DatasetArtifact
- ExperimentManifest binds strategy hash, dataset hashes/sources, configuration, execution assumptions, code revision and timestamp into one reproducible manifest hash
- ResearchArtifact can be bound to the exact experiment manifest

## Current deployment status

**Engineering + research + deterministic paper only. Live-money execution is intentionally not enabled.**

The system is designed so live connectivity can be added behind the existing broker abstraction after the remaining controls below are completed and validated.

## High-priority remaining work

1. richer portfolio risk: contract multipliers, lots/ticks, futures margin/MTM, options Greeks, multi-currency cash, correlation/concentration, VaR/CVaR and stress limits
2. production historical-data adapters and point-in-time dataset ingestion for target markets
3. real provider adapters for selected AI models with secrets isolation, rate limits, model/version manifests and evaluation/calibration
4. concrete broker sandbox connectors one-by-one, beginning with an explicitly chosen venue/account
5. complete broker reconciliation: cash/balances, historical fills, venue-specific order edge cases and reconnect fault injection
6. multi-timeframe live context builder and HTF aggregation service
7. real options-chain/Greeks/IV source adapter
8. point-in-time macro/news ingestion into KnowledgeFirewall
9. portfolio-level live paper supervisor, alerts, metrics/dashboard and incident runbooks
10. extended walk-forward, Monte Carlo and paper validation on real historical datasets before any live strategy can become eligible
11. canary deployment/rollback tooling after all earlier gates pass

## Non-negotiable authority chain

```text
Data quality / point-in-time evidence
             |
             v
9+ concurrent specialist agents / optional additional AI models
             |
             v
CEO synthesis
             |
             v
Agent evidence risk policy
             |
             v
Independent portfolio RiskEngine
             |
             v
Order state machine -> Broker/Paper adapter -> Fill
             |
             v
Portfolio ledger + WAL + reconciliation + audit
```

No AI model, agent majority, CEO memo or research agent can skip any downstream authority layer.
