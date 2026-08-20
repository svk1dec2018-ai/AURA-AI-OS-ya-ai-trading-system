# AURA Command Center

AURA includes a deterministic command/privilege boundary plus a local-first mobile/PWA operator surface for a Jarvis-style text or voice interface.

Supported intent classes include market scan, system/status, risk status, positions/portfolio, explanation, research request, paper control, and live control. The typed command model remains broker-independent. Read-only commands cannot become orders, research and paper actions have separate privilege levels, and `LIVE_CONTROL` is disabled by default. Even if deployment governance later enables a live handler elsewhere, the command model itself does not bypass AURA's independent `RiskEngine`, execution policy, reconciliation, or human live approval.

## Command Center v2

Start the current command center with:

```bash
python examples/run_command_center.py
```

Then open `http://127.0.0.1:8765`. Supported browsers may expose speech-to-text through the browser Web Speech API; typed commands always remain available. Voice produces text which still passes through the same deterministic command classifier, so speech does not create a second authority path.

V2 adds a governed owner cockpit and freshness-gated read model:

- Opportunity Radar table with deterministic rank, CEO confidence, canonical technical alignment, risk flags, source time, and actionable/blocked state;
- risk and portfolio visibility;
- read domains for opportunities, portfolio, risk, agents, data, brokers, system, and research;
- domain provenance, observation time, age, and SHA-256 payload checksum;
- stale snapshots are marked unavailable and their payload is withheld instead of being treated as current evidence;
- missing providers return explicit unavailable responses rather than fabricated values;
- deterministic `scan markets`, `risk status`, `portfolio`, and `explain for SYMBOL` read commands;
- research requests remain durable, checksummed, idempotent, `pending_human_review`, and `auto_promotion_allowed=false`.

The PWA/API surface remains deliberately narrower than the core runtime:

- it has no broker submit/cancel adapter;
- live-money intents are rejected with HTTP 403 before handler execution;
- paper execution-control intents are also rejected by this observation/research surface;
- stale market/risk/portfolio snapshots are not returned as usable payloads;
- it does not invent target, stop-loss, quantity, fills, P&L, positions, or market values;
- strategy research cannot auto-promote into paper/live deployment.

## Unified Opportunity Radar inputs

`aura/strategy/features.py` provides the shared closed-candle feature calculations used by the radar foundation. Current canonical features include EMA 8/21/50/200, Wilder RSI, MACD, Bollinger Bands, ATR, Supertrend, VWAP, OBV, VPT, and rolling support/resistance. Warm-up periods return explicit `null`/unavailable features instead of synthetic values.

`aura/runtime/opportunity_radar.py` consumes existing governed `MarketScanResult` candidates. Ranking combines CEO confidence, specialist agreement, canonical directional feature alignment, adversarial disagreement, and risk flags. It creates no order request and has no sizing or execution authority. A candidate still needs the separate financial risk coordinator before any paper order can exist.

Runtime producers can publish already-governed snapshots through `OperatorReadModel`. The read model rejects future timestamps, backward time travel, non-finite/non-JSON payloads, and stale data use.

## Network exposure

The default bind is loopback-only:

```text
AURA_COMMAND_CENTER_HOST=127.0.0.1
AURA_COMMAND_CENTER_PORT=8765
AURA_COMMAND_CENTER_QUEUE=artifacts/operator/research_requests.jsonl
AURA_COMMAND_CENTER_TOKEN=
```

Binding to a non-loopback address fails closed unless `AURA_COMMAND_CENTER_TOKEN` contains at least 32 characters. API callers must then send that token as `Authorization: Bearer ...`. Never commit the token.

## API

Core endpoints:

```text
GET  /api/health
GET  /api/status
GET  /api/overview
GET  /api/opportunities
GET  /api/portfolio
GET  /api/risk
GET  /api/agents
GET  /api/data
GET  /api/brokers
GET  /api/system
GET  /api/research
POST /api/command
```

Example:

```bash
curl http://127.0.0.1:8765/api/status
curl http://127.0.0.1:8765/api/opportunities
curl -X POST http://127.0.0.1:8765/api/command \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: owner-request-001' \
  -d '{"text":"research XAUUSD regime filters"}'
```

A request such as `go live` or `paper start` is rejected by design. Enabling controlled live money requires the separate Phase 0-15 governance process, broker-origin validation, independent risk approval, reconciliation evidence, and explicit human approval. Command Center v2 is not a shortcut around those controls.
