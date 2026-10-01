# AURA Prime — Trader + Developer Audit

Date: 2026-09-19

## Executive judgment

The current AURA repository has a strong governed trading core, but it is not yet the cleanest possible final product architecture.

What is already strong:
- deterministic risk/execution authority chain
- durable WAL/checkpoint/reconciliation
- causal backtest and research governance
- MT5 DEMO safety guard
- multi-agent decision framework
- extensive Python test inventory
- production CI, CodeQL, container build
- Redis fleet foundation and live dashboard transport

What is holding it back:
- 588 repository files, 429 Python files and 63 entrypoints create avoidable operator complexity
- the repository audit reports 98 stub/incomplete candidates; 12 are review-required
- 23 source modules have no direct import-based test mapping
- the current dashboard is concentrated in one ~32 KB component plus ~31 KB global CSS
- the current fleet workers are infrastructure workers; generic services publish health but do not yet implement the complete Nexus-style business pipeline
- no production dependency on XGBoost, LightGBM, sklearn, HMM, ONNX, DuckDB, Polars, Prometheus or OpenTelemetry is present
- model registry/drift policies exist, but not a full trained-model artifact lifecycle
- frontend has no Playwright/Vitest/Cypress suite
- API service still uses Python http.server rather than a typed ASGI gateway
- all-market architecture exists, but all-market live execution maturity is not equal across providers
- there are multiple historical launchers and legacy web surfaces, increasing the chance that a beginner starts the wrong runtime

## Findings that must change in AURA Prime

### P0 — Product truth
1. One canonical operator path: setup -> configure -> start -> doctor -> stop.
2. Dashboard must never show fabricated metrics. Missing data must render as unavailable/gated.
3. Provider cards must distinguish public data, credentialed data, demo execution and live execution.
4. Real-money authority remains downstream of broker evidence and human approval.

### P0 — Runtime
1. Every distributed service must have an explicit role-specific handler before it is called active.
2. Service health and business readiness must be separate states.
3. All event payloads require schema version, correlation id, source, observed time and received time.
4. Market and model events must be replayable.
5. No LLM provider may be in the latency-critical execution path.

### P0 — Trading
1. Closed-candle features only for strategy decisions.
2. Current tick only for execution/quote display.
3. Purged/embargoed time-series validation for model research.
4. Champion/challenger promotion must require enough samples plus cost/slippage stress.
5. Risk caps remain immutable from AI/ML code.
6. No martingale, unlimited grid or averaging-down recovery.

### P1 — Data + ML
1. Add a real feature store/trade-memory layer using a local analytical store.
2. Add actual optional ML adapters: sklearn/XGBoost/LightGBM/HMM/ONNX.
3. Keep deterministic fallback and calibration.
4. Version/checksum model artifacts with rollback.
5. Record predictions, features, regime, decision, fill, MAE/MFE and outcome for every candidate.
6. Drift monitoring must trigger research, not silently rewrite live policy.

### P1 — API + Observability
1. Typed ASGI API for REST + WebSocket/SSE.
2. Prometheus-compatible metrics.
3. Structured JSON logs with correlation IDs.
4. Health, readiness and liveness separated.
5. Crash/restart counts visible in UI.

### P1 — Dashboard
1. Replace monolithic screen with modular control-room panes.
2. Central AURA/JARVIS orb is a command surface, not decorative-only UI.
3. Trading chart stays dominant; AI reasoning and risk sit around it.
4. Global Cmd/Ctrl+K command palette.
5. Live connection status on every real-time panel.
6. Mobile PWA and desktop layouts.
7. Frontend unit/E2E tests.

### P2 — Free-first intelligence
Use public/no-key sources when legally/reliably available and account-bound official feeds where required.
Do not claim Indian exchange real-time data is universally free.

## Clean-repo policy

AURA Prime will migrate verified code, not repository clutter.

Keep:
- financial core
- risk
- execution state machine
- portfolio/WAL/reconciliation
- causal backtest/research
- agent contracts/orchestrator
- verified MT5 DEMO adapter
- data quality and provider adapters
- production gates
- tests that validate migrated behavior

Replace/refactor:
- legacy web server/UI
- duplicate operator launchers
- generic-only fleet workers
- giant dashboard component
- manual polling where an event stream exists

Exclude from the clean source tree:
- generated PDFs
- generated governance evidence committed only as historical artifacts
- deprecated static dashboard
- obsolete launchers
- duplicated docs
- runtime outputs

## Current blocker to second repository

The target repository `svk1dec2018-ai/aura-new-by-arena` is readable by the connected GitHub integration but write operations return GitHub API 403 Resource not accessible by integration. The rebuild is therefore being staged on `aura-prime-rebuild` until target-repo write access is granted.
