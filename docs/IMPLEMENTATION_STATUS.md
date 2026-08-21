# AURA AI OS — Current Implementation Status

This document is the current source of truth for what is implemented in code versus what remains externally gated. See `PRODUCTION_READINESS.md` for deployment and release procedures.

> **Mandatory governance status:** Code presence is no longer a phase-completion
> claim. The machine-readable authority is
> `artifacts/governance/phase_gate_status.json`. Phases 0–10 are PASS; Phases 11–15
> remain BLOCKED until their named validation evidence is produced and accepted.
> Existing later-phase code is preserved as implementation inventory, not
> retroactive gate certification.

## Current classification

**AURA is a production-deployable paper/demo research service candidate.**

It is **not yet certified for unrestricted real-money production**. Real-money eligibility intentionally requires broker-origin forward evidence, an APPROVED immutable strategy version, explicit human approval, healthy operational state and a passing `ProductionReleaseGate` manifest.

No backtest, LLM opinion, public-data shadow result, paper champion or code-only test can bypass that boundary.

Phase 11 now has a secret-free external broker evidence schema and read-only
verifier. It rejects self-attested sources, duplicated observations, tampered
content, non-causal timestamps, incomplete fills and unstable reconciliation.
This is readiness infrastructure only: Angel One remains read-only, MT5 remains
demo-only, and Phase 11 remains BLOCKED pending accepted external evidence.
An offline intake command can now load sealed evidence plus an owner-controlled
two-reviewer attestation registry and emit a deterministic assessment. It cannot
connect to a broker, mutate the phase ledger, authorize execution, or turn code
approval into financial authorization.
The evidence recorder can now convert existing filled `OrderState` and
`ReconciliationReport` objects into that sealed format without serializing raw
broker/order/fill identifiers, symbols, prices or reconciliation details. It is
an adapter integration boundary, not proof that either broker has executed a live
order.
Already-sealed evidence can now be persisted in a restart-safe append-only archive
that reuses AURA's checksummed write-ahead log, verifies sequence/content/event
bindings, and links records by prior evidence hash. Strong protection against an
administrator deleting or replacing an archive prefix is available through a
sealed checkpoint export/verify CLI, provided the checkpoint or printed digest is
copied to an owner-controlled system outside the archive host.
A custody CLI now validates an eligible two-broker batch before any write, appends
it idempotently, anchors the resulting WAL prefix and emits a content-sealed
receipt. Blocked evidence produces no archive/checkpoint/receipt mutation, and the
receipt cannot update the phase ledger or grant execution authority.

## Implemented and wired

### Financial and execution core

- one deterministic candle fill/cost model shared by backtest and paper execution
- market/limit/stop gap rules, adverse slippage, fees and contract multipliers
  use that shared model rather than duplicated simulator math
- canonical candles, orders, fills and portfolio snapshots
- broker-neutral instruments and venue symbol mapping
- shared signal -> independent RiskEngine -> order path
- position-aware reductions/closes vs new exposure
- kill switch, order-notional, gross-exposure, daily-loss and drawdown controls
- contract-aware accounting and exposure semantics
- deterministic order state machine
- idempotent fills, partial-fill VWAP and overfill rejection
- cash/position ledger with fees, realized/unrealized P&L and long/short flips
- deterministic PaperBroker with market/limit/stop simulation

### Durable state, restart and reconciliation

- checksum-protected append-only financial WAL
- event/correlation IDs and monotonic sequencing
- typed financial event journal
- atomic checkpoints + WAL-tail replay
- duplicate-fill-safe deterministic recovery
- broker/local order and position reconciliation
- critical divergence freezes new risk rather than silently mutating state
- connector circuit breaker and idempotency-aware retry guard

### Market-data safety and multi-market feeds

- fail-closed provider-neutral candle ingestion boundary: malformed or partial
  batches expose no candles to decision consumers
- mandatory quality gates at multi-agent decision and multi-market scanner boundaries
- machine-readable latest-candle lag measurement in every non-empty quality report
- duplicate/out-of-order/gap/stale/future-data gates
- session-aware candle aggregation including second-level research bars
- cross-feed price sanity/outlier guard
- Kraken and Binance foundations
- public/no-key Coinbase, Bybit and OKX live market-data adapters
- Exness/MetaTrader 5 DEMO market-data integration and guarded demo execution adapter
- Dhan instrument master, broad ticker, FULL depth/OI/volume, history, option-chain and option-context services
- Shoonya read-only live/historical data adapter
- Flattrade read-only live/historical data adapter
- OANDA v20 practice/live read-only market-data adapter

### Multi-agent and multi-model intelligence

The intelligence desk contains deterministic specialists plus optional local/provider AI agents. Core roles include:

1. HTF Bias
2. SMC/ICT Structure
3. Technical
4. Volume/VWAP
5. Forecast
6. Options/Volatility
7. Macro/Sentiment
8. Cross-Market
9. Regime
10. Execution Quality

Implemented AI infrastructure:

- concurrent specialist orchestration with timeout/failure isolation
- structured point-in-time AgentEvidence with trust/provenance
- multi-model Ollama council using structured decisions
- raw model private reasoning is not persisted as decision evidence
- Bull/Bear/Counterfactual adversarial deliberation
- deterministic CEO synthesis
- AgentRiskPolicy before financial RiskEngine
- contextual agent/model reliability learning by role, market and regime
- adaptive model router with controlled exploration rather than static round-robin
- forward counterfactual scoring even when the CEO skips a trade
- persistent agent/model reliability state across brain-policy changes

### Specialist intelligence

- EMA/RSI/MACD/Bollinger/Keltner technical evidence
- SMC/ICT-style liquidity sweep, BOS/CHoCH and fair-value-gap primitives
- VWAP, relative volume, OBV/VPT participation evidence
- HTF context and trend/chop regime evidence
- Dhan option-chain PCR/IV/Greeks/liquidity context
- execution spread/slippage/top-book checks
- cross-market context
- trusted macro/news context via KnowledgeFirewall
- no fabricated dealer positioning or directional options evidence when source data cannot support it

### Free/official intelligence plane

- point-in-time source/trust model
- RBI/SEBI official-feed support
- GDELT integration
- optional FRED, SEC EDGAR and Alpha Vantage news/sentiment integrations
- timestamped live intelligence cache
- future-observed knowledge rejected from current decisions
- contradictory trusted claims fail closed rather than silently choosing one

### Research, strategy invention and self-evolution

- immutable strategy genomes and bounded gene spaces
- autonomous strategy DSL/factory
- safe mutation/crossover/population evolution
- live shadow strategy lab
- AI Strategy Architect generating bounded component proposals
- AI output cannot set leverage, risk limits, order quantity, kill switch or broker permissions
- causal blueprint compiler converting supported immutable blueprints into executable strategies
- event-driven causal backtesting with next-bar execution semantics
- multi-symbol shared-portfolio backtesting
- leakage-safe walk-forward testing
- block-bootstrap Monte Carlo robustness testing
- deterministic research manifests and dataset/source identity
- research -> backtest -> robustness -> paper -> human approval lifecycle
- demo/paper champion/challenger evolution
- forward-only live outcome labeling
- missed-opportunity, wrong-direction and capture-rate learning
- restart-safe unresolved opportunity checkpoints and idempotent replay into the
  safe online learner
- historical/public data may accelerate research but cannot masquerade as broker-forward live proof

### Live/paper runtimes

- public no-key crypto live-data runner
- public no-key autonomous strategy lab runner
- public multi-AI council runner
- MT5 all-market internal-paper runner
- MT5 self-evolving paper runner
- Dhan Indian-market self-evolving paper runner
- broad radar -> deep shortlist architecture so expensive AI is not called on every market tick
- bounded AI in-flight capacity so slow local models cannot stall market ingestion

### Production operations added

- `aura.ops.preflight.ProductionPreflight`
  - Python/runtime-path checks
  - connector configuration checks
  - non-live modes fail if live-risk acknowledgement leaks into their environment
  - LIVE requires APPROVED strategy + explicit human approval + exact live-risk acknowledgement
- `aura.ops.health.HealthReport`
  - HEALTHY / DEGRADED / UNHEALTHY contract
  - only HEALTHY permits new risk
- `aura.ops.release_gate.ProductionReleaseGate`
  - requires broker-origin forward evidence for a live canary
  - rejects `LIVE_PUBLIC`, historical and synthetic evidence for live release
  - default minimum gate: 1,000 forward broker trades, 30 forward days, PF >= 1.10, positive expectancy, DD <= 10%, zero critical/reconciliation/data-integrity incidents
- production preflight CLI
- production release-evidence evaluator CLI
- `.env.example` with secrets intentionally blank
- non-root Docker image for Linux/public HTTP/WebSocket services
- separate Windows/MT5 deployment guidance
- production readiness/runbook documentation

### CI and repository security

Normal CI is non-self-modifying and validates:

- Python 3.11 and 3.12
- dependency consistency (`pip check`)
- bytecode compile smoke
- Ruff
- complete pytest suite
- public paper production-preflight smoke
- Python distribution build
- Docker production image build after test matrix passes

Additional repository controls:

- CodeQL Python security scanning on push/PR plus weekly schedule
- Dependabot for pip and GitHub Actions dependencies
- `.env` ignored by git
- self-modifying patch-and-push workflow removed from normal production CI

## What remains before real-money production certification

These items require external broker/account/runtime evidence and cannot be manufactured by repository code alone:

1. credential-backed long-duration operation on the intended host/VPS
2. 1,000+ forward broker-origin paper/demo decisions/trades over 30+ elapsed days under the default release policy, or a stricter market-specific policy
3. validation across trend, chop, high-volatility, news, reconnect and market-open/close regimes
4. broker-specific order rejection/fill/partial-fill/reconnect/reconciliation fault testing
5. venue-specific margin, freeze/lot/tick, expiry/settlement and liquidation-headroom validation
6. zero unresolved critical incidents, reconciliation failures or data-integrity incidents in the release window
7. immutable strategy must reach `PAPER_VALIDATED`, then a HUMAN actor must transition it to `APPROVED`
8. `ProductionReleaseGate` must produce an eligible manifest from `LIVE_BROKER` evidence
9. explicit live canary approval/change ticket and exact live-risk acknowledgement
10. smallest-size canary first; capital/symbol scope increases require a separate approval

## Authority chain

```text
Point-in-time market/news/options data
              |
              v
Fast scanner / research strategy farm
              |
              v
Deterministic specialists + optional multiple AI models
              |
              v
Bull / Bear / Counterfactual deliberation
              |
              v
Reliability-weighted deterministic CEO synthesis + reproducible decision trace
              |
              v
Agent evidence policy
              |
              v
Independent portfolio RiskEngine
              |
              v
Order state machine -> Paper/Demo/Broker adapter -> Fill
              |
              v
Portfolio ledger + WAL + reconciliation + audit
              |
              v
Outcome / missed-trade / reliability / evolution learning
```

No AI model, agent majority, CEO memo, strategy architect or research loop can skip a downstream authority layer.
