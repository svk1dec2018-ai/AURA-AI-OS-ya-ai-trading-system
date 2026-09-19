# AURA AI OS — Final Production Review — 2026-09-19

## Executive status

**Software deployment class:** production-deployable paper/demo candidate.

**Real-money class:** blocked by design pending external broker evidence. This is not a software defect; it is the enforced release boundary.

## Verified architecture

### Core financial safety
- deterministic canonical market/order/fill/portfolio contracts
- broker-neutral instrument mapping
- independent RiskEngine
- kill switch, daily-loss, drawdown, gross exposure and order-notional controls
- order state machine, idempotent fills and partial-fill VWAP
- append-only financial WAL, checkpoints and deterministic recovery
- broker/local reconciliation with fail-closed risk freeze

### Intelligence and learning
- deterministic specialists
- multi-agent orchestration
- Bull/Bear/Counterfactual deliberation
- deterministic CEO synthesis
- contextual reliability learning
- model routing
- strategy factory, mutation/crossover and shadow research
- leakage-safe walk-forward and robustness infrastructure
- champion/challenger paper lifecycle
- forward-only outcome and missed-opportunity learning

### Production/runtime
- Windows MT5 DEMO bridge
- premium Next.js dashboard
- Redis Streams distributed fleet
- nine service roles
- restart supervisor
- SSE dashboard event stream
- one-click setup/start/stop/doctor
- secret-safe local configuration
- CodeQL and CI production gates

## Market coverage

### Execution/readiness
- MT5: protected DEMO integration implemented and broker-side readiness probe available.
- Dhan: Indian-market data/options stack implemented; live order production remains externally gated.
- Angel One: read-only account/quote/reconciliation adapter implemented; submit/cancel intentionally locked pending broker validation.
- OANDA: practice/live read-only market-data adapter implemented; order routing intentionally locked.
- Binance/Kraken: market-data foundations implemented; authenticated production execution is not certified.
- Public crypto: Coinbase/Bybit/OKX no-key research/live-data paths available.

This means AURA is architecturally all-market, but not every provider is currently certified for live order routing.

## Governance status

Machine-readable phase ledger:
- phases 0-10: PASS
- phase 11 broker live readiness: BLOCKED pending external evidence
- phases 12-14: PASS
- phase 15 controlled live deployment: BLOCKED because Phase 11 is not PASS

The final production doctor treats 11/15 as non-blocking for paper/demo and blocking for live-money eligibility.

## Final setup surface

Canonical files:
- `FINAL_SETUP_AURA.cmd`
- `CONFIGURE_AURA.cmd`
- `START_AURA_PRODUCTION.cmd`
- `AURA_PRODUCTION_DOCTOR.cmd`
- `STOP_AURA_PRODUCTION.cmd`

The private `.env.local` is ignored by Git.

## Release interpretation

When the final doctor reports:

```text
Software production ready: YES
Live-money eligible: NO
```

the correct interpretation is:
- the software/service stack is deployable for demo/paper
- the system may collect required forward evidence
- live financial authority remains intentionally unavailable

Do not relabel this as unrestricted live-production until the release gate and external evidence requirements pass.
