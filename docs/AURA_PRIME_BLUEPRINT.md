# AURA Prime — Final Architecture Blueprint

## Design principle

AURA Prime is a deterministic trading operating system with AI/ML as bounded intelligence, not as financial authority.

```text
                        AURA PRIME CONTROL ROOM
                                 |
                      Typed API + SSE/WebSocket
                                 |
            +--------------------+--------------------+
            |                    |                    |
         JARVIS              LIVE MARKET           SYSTEM
       command orb             workspace            health
            |                    |                    |
            +--------------------+--------------------+
                                 |
                         EVENT / DATA PLANE
                                 |
        +------------+-----------+-----------+-------------+
        |            |                       |             |
      DATA        FEATURES                NEWS/MACRO     MEMORY
   connectors     MTF/context             intelligence   DuckDB
        |            |                       |             |
        +------------+-----------+-----------+-------------+
                                 |
                           DECISION PLANE
                                 |
        deterministic specialists + optional ML ensemble
                                 |
                  Bull / Bear / Counterfactual
                                 |
                    deterministic CEO synthesis
                                 |
                    independent AgentRiskPolicy
                                 |
                        HARD FINANCIAL PLANE
                                 |
              RiskEngine -> Order FSM -> Broker adapter
                                 |
                    Fill -> Ledger -> WAL -> Reconcile
                                 |
                         OUTCOME / LEARNING
                                 |
              drift -> research -> challenger -> approval
```

## Proven-project lessons incorporated

- QuantConnect LEAN: modular event-driven engine and multi-market/live separation.
- NautilusTrader: one deterministic event-driven architecture across research, simulation and live execution.
- Microsoft Qlib: repeatable quant workflow and model research.
- Microsoft RD-Agent: automated factor/model research loop.
- TradingAgents: specialist analyst/research/risk roles with structured outputs.
- FreqAI: adaptive retraining outside the inference/trade loop.
- Hummingbot: strict connector interfaces and encrypted-secret discipline.
- VeighNa/vn.py: production-grade event engine and gateway model.
- TradingView Lightweight Charts: high-performance interactive financial charts.
- JARVIS/HUD open-source projects: voice-first command surface, state-reactive orb and permission-gated actions.

## License policy

Direct code reuse is allowed only when compatible with the target repository license and attribution obligations.

Safe reference/reuse families:
- MIT
- Apache-2.0

Architecture-only / isolated consideration:
- LGPL-3.0 components
- GPL-3.0 components
- AGPL-3.0 components

Nexus is AGPL-3.0 and is not copied into AURA Prime. Its useful service topology is reimplemented independently.

## Service model

Canonical logical services:
1. gateway
2. market-data
3. feature-engine
4. model-inference
5. intelligence-agents
6. portfolio-risk
7. execution
8. research-learning
9. observability

Each service has:
- liveness
- readiness
- event input/output contract
- retry/backoff policy
- explicit financial authority flag
- structured metrics

Only portfolio-risk and execution may ever declare financial authority.

## Live-data truth matrix

### Key-free public
- Coinbase public market data
- Kraken public market data
- Bybit public market data
- OKX public market data
- GDELT
- SEC EDGAR
- RBI/SEBI public feeds where applicable

### Free/account or free-key dependent
- MT5 broker DEMO/live quote feed
- broker APIs such as Angel One/Shoonya/Flattrade depending account rules
- FRED free key
- Alpha Vantage free tier where limits are acceptable

### Not assumed free
- licensed Indian exchange real-time data
- premium news
- institutional depth/alternative data

AURA Prime must operate without paid AI APIs. Ollama/local models remain the default free intelligence route.

## Dashboard composition

Desktop:
- left: market universe/watchlists/navigation
- center: TradingView Lightweight Charts workspace
- right: AI verdict, agent constellation, risk radar, execution state
- bottom: orders/fills/positions/journal
- top: global market ticker + connection status + command palette
- floating center/right: AURA orb with listen/think/speak/alert states

Mobile/PWA:
- chart-first tabs
- voice orb
- positions/risk card
- alert approvals
- no dense desktop-only tables

## Promotion model

Research candidate -> causal backtest -> walk-forward -> Monte Carlo -> shadow ->
paper/demo -> champion/challenger evidence -> human strategy approval -> smallest canary.

AI can propose and test. AI cannot:
- change max risk
- change max drawdown
- enable live money
- add/withdraw funds
- bypass broker reconciliation
- self-approve deployment
