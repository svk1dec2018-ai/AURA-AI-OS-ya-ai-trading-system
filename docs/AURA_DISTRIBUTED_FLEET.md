# AURA Distributed Fleet — Nexus-style architecture, all-market scope

AURA is adopting a distributed event-driven architecture inspired by proven public trading-system patterns while preserving AURA's existing governance, point-in-time safety, reconciliation, and independent RiskEngine.

This implementation is **not copied from Nexus Trader source code**. Nexus Trader is AGPL-3.0. AURA therefore reimplements the architecture and behavior independently to avoid accidental license contamination.

## Current fleet foundation

AURA now defines nine cooperating service roles:

1. aura-api
2. aura-data
3. aura-features
4. aura-ml
5. aura-agents
6. aura-news
7. aura-risk
8. aura-executor
9. aura-monitor

The services communicate through a common versioned event envelope and a Redis Streams-compatible bus. Tests can use the deterministic in-memory bus. Redis is an optional distributed dependency.

Only **aura-risk** and **aura-executor** are allowed to declare financial authority. ML, agents, news, data and dashboard services cannot submit orders or change risk authority.

## All-market provider registry

The first registry covers:

- MetaTrader 5 — Forex, commodities, global indices, crypto CFDs
- Dhan — India equities and F&O
- Angel One SmartAPI — India equities and F&O
- Binance — crypto spot and derivatives
- Kraken — crypto spot and derivatives
- OANDA — Forex, commodities and global indices

The registry reports only whether required environment-variable names are configured. It never returns secret/API-key values to the dashboard.

At this stage, MT5 is the only provider marked execution-supported in the distributed registry. Other providers remain credential-gated / integration-in-progress until authenticated adapter conformance and broker-origin evidence pass.

## Event streams

The foundation defines these event families:

- market.tick
- market.candle
- features.vector
- ml.vote
- agents.verdict
- news.signal
- risk.decision
- execution.order
- execution.fill
- research.event
- system.health

The Redis implementation uses namespaced Redis Streams. The in-memory implementation follows the same publish/read contract for deterministic tests.

## Setup

Install the distributed dependency:

    pip install -e ".[distributed]"

Start Redis locally, for example with Docker:

    docker run -d --name aura-redis -p 6379:6379 redis:7-alpine

Optional environment variable:

    AURA_REDIS_URL=redis://127.0.0.1:6379/0

Check the fleet manifest:

    aura-fleet

Check Redis connectivity:

    aura-fleet --check-redis

The premium dashboard exposes **Distributed Fleet** and shows the service topology plus all-market provider credential gates.

## API keys and secrets

Do not paste real API keys into ChatGPT, GitHub issues, screenshots or source files.

Use local environment variables / a private .env that is excluded from Git. The repository contains only placeholder names in .env.example.

Provider credentials are connected only when their actual adapter is being validated.

## Next implementation slices

1. Real Redis worker processes for data/features/ML/agents/news/risk/executor/monitor.
2. WebSocket/SSE gateway consuming Redis Streams.
3. Per-symbol ML ensemble: XGBoost, LightGBM, LSTM, HMM, Isolation Forest.
4. Trade-memory store and walk-forward retraining.
5. Bull/Bear/Arbitrator agents connected to the ML/event pipeline.
6. News/calendar + FinBERT-compatible sentiment worker.
7. PPO lifecycle challenger in shadow/research mode.
8. Authenticated Dhan/Angel/Binance/Kraken/OANDA adapters.
9. Supervisor with crash restart and service health.
10. Broker-origin forward-validation campaign before any controlled live-money eligibility.

Passing software tests does not establish profitability. All strategy and model candidates still require AURA's causal backtest, out-of-sample, walk-forward, paper/DEMO and risk-evidence gates.

## One-click Windows fleet runtime

After running `START_AURA2.cmd` once, install/start Docker Desktop and then double-click:

`START_AURA_FLEET.cmd`

The starter:
- installs AURA's optional Redis dependency
- starts/reuses the `aura-redis` Redis 7 container
- verifies Redis connectivity
- starts the nine-service AURA supervisor
- writes fleet logs under `runtime/fleet/`

Open **AURA 2 -> Distributed Fleet** to see live SSE service heartbeats.

To stop the distributed services and Redis without closing MT5 or the dashboard, double-click:

`STOP_AURA_FLEET.cmd`

Each fleet worker also exposes a local read-only health endpoint on its reserved port (9100-9108). The generic workers publish only health telemetry until a role-specific business handler is attached; they do not fabricate ML votes, agent verdicts, risk decisions or orders.
