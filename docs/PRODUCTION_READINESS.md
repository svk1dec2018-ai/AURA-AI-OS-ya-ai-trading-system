# AURA AI OS — Production Readiness Runbook

This document defines the operational path from a clean checkout to a production-deployable
paper/demo service and, later, a tightly gated live-money canary.

## What "production ready" means in AURA

AURA separates software production readiness from trading-strategy profitability.

- **Production-deployable paper/demo** means the code, package, durable state, secrets,
  health checks, CI and recovery controls are suitable for an unattended service.
- **Live-money eligible** additionally requires a human-approved strategy plus measured
  forward broker evidence that passes `ProductionReleaseGate`.
- No backtest, public-data shadow result, LLM opinion or paper champion can by itself
  enable live-money execution.

## Recommended hosts

### All-in-one with Exness / MetaTrader 5

Use Windows 11 Pro or Windows Server with the official MetaTrader 5 terminal installed.
The `MetaTrader5` Python package talks to the local terminal and is intentionally not part
of the Linux container image.

Recommended starting host for broad scans + local AI models:

- 4+ modern CPU cores; 8+ preferred
- 16 GB RAM minimum; 32 GB preferred for multiple local models
- SSD storage with persistent runtime/WAL backup
- stable wired network when possible
- OS clock synchronization enabled

### Linux / Docker

The repository Dockerfile is suitable for brokerless public-data services and HTTP/WebSocket
market-data integrations such as Dhan, Shoonya, Flattrade and OANDA. Do not claim MT5 support
inside this Linux image.

## Clean installation

```powershell
# Windows
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pip install MetaTrader5
ruff check aura tests examples
pytest -q
python -m build
```

```bash
# Linux
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
ruff check aura tests examples
pytest -q
python -m build
```

## Secrets

Use `.env.example` only as a list of variable names. Set real secrets in the service/process
environment or an OS secret manager. Never commit `.env`, broker passwords, access tokens,
TOTP seeds, API keys or live approval tokens.

Before starting a service, run the fail-closed preflight:

```powershell
python examples/run_production_preflight.py --mode paper --connector public
```

MT5 demo:

```powershell
python examples/run_production_preflight.py --mode demo --connector mt5_demo
```

Dhan live-data + internal paper:

```powershell
python examples/run_production_preflight.py --mode paper --connector dhan
```

The process must not start if a required secret/config value is absent or the durable runtime
path cannot be written.

## First unattended production candidate: public live data

No broker credentials are required:

```powershell
python examples/run_public_crypto_live.py
```

Strategy research farm:

```powershell
python examples/run_free_public_strategy_lab.py
```

Multi-AI council with local Ollama models:

```powershell
$env:AURA_FREE_AI_PRESET="balanced5"
$env:AURA_OLLAMA_KEEP_ALIVE="0"
$env:AURA_AI_OPINIONS_PER_ROLE="1"
aura-free-ai probe
python examples/run_free_public_ai_council.py
```

The preset resolves to five local models and approximately 20 GB of downloads. Requests are
serialized and models unload after each response by default. No AI API key or broker credential
is used; model licenses and local hardware costs still apply.

## MT5 / Exness demo candidate

Required environment:

```text
AURA_MT5_DEMO_LOGIN
AURA_MT5_DEMO_PASSWORD
AURA_MT5_DEMO_SERVER
AURA_MT5_TERMINAL_PATH   # optional
```

Run:

```powershell
python examples/run_mt5_self_evolving_paper.py
```

The all-market learning path uses verified DEMO market access while AURA's default
self-evolution execution remains internal paper. Do not replace the demo guard with a live
account credential.

## India / Dhan paper candidate

Required environment:

```text
AURA_DHAN_CLIENT_ID
AURA_DHAN_ACCESS_TOKEN
```

Run:

```powershell
python examples/run_dhan_self_evolving_paper.py
```

This is live-data-first paper validation. It is not a live order runner.

## Operational monitoring

Treat these as blockers for new risk:

- stale or future market data
- broker/data-feed disconnection outside bounded recovery
- reconciliation mismatch
- corrupted WAL/checkpoint state
- kill switch engaged
- runtime disk not writable or nearly full
- repeated order rejection / invalid contract metadata
- unresolved data-integrity incident

`aura.ops.health.HealthReport` provides a standard HEALTHY / DEGRADED / UNHEALTHY contract.
Only HEALTHY permits new risk. Existing positions must still be allowed to reduce/flatten
through the independent risk/execution path.

## Backups and recovery

Persist the entire runtime directory on durable storage. At minimum retain:

- financial WAL
- agent/decision audit WAL
- checkpoints
- reconciliation records
- strategy/evolution journals
- paper champion/challenger state
- release manifests

Do not truncate the immutable financial WAL merely because a newer checkpoint exists.
Test restart and replay after every meaningful release.

## Release gate for a live-money canary

A candidate must first be `StrategyStage.APPROVED`, which requires a human actor under the
existing strategy governance firewall. Then prepare measured broker-forward evidence JSON:

```json
{
  "strategy_id": "example",
  "strategy_version": "v1",
  "strategy_stage": "APPROVED",
  "forward_live_trades": 1500,
  "forward_live_days": 45,
  "max_drawdown_pct": "6.5",
  "profit_factor": "1.35",
  "expectancy": "0.18",
  "critical_incidents": 0,
  "reconciliation_failures": 0,
  "unresolved_data_integrity_events": 0,
  "source": "LIVE_BROKER"
}
```

Evaluate it:

```powershell
python examples/evaluate_production_release.py evidence.json
```

Default policy requires at least 1,000 forward broker trades, 30 forward-live days,
positive expectancy, profit factor >= 1.10, max drawdown <= 10%, zero critical incidents,
zero reconciliation failures and zero unresolved data-integrity events. These are minimum
engineering gates, not a promise of profitability and may be made stricter for a given market.

`LIVE_PUBLIC`, historical, backtest and synthetic evidence are intentionally rejected for
live release eligibility.

## Explicit live-money acknowledgement

Even an eligible release manifest is insufficient by itself. Live preflight additionally
requires:

```text
AURA_HUMAN_LIVE_APPROVAL_ID=<external approval/change ticket>
AURA_LIVE_TRADING_ENABLED=I_UNDERSTAND_AND_APPROVE_LIVE_RISK
```

Both values must remain unset in research, paper and demo environments.

## Canary policy

When a future live broker adapter is approved:

1. start with the smallest venue-valid order size;
2. one symbol / one strategy / one account slice;
3. keep the global kill switch and daily loss limit active;
4. reconcile every order/fill/position/cash state;
5. block scale-up after any critical incident;
6. require a separate human approval for increasing capital or scope;
7. preserve immutable release and runtime evidence for rollback.

## CI and security

Every push/PR runs:

- Python 3.11 and 3.12
- dependency consistency (`pip check`)
- bytecode compile smoke
- Ruff
- full pytest suite
- production public-paper preflight smoke
- Python distribution build

GitHub CodeQL runs on pushes/PRs and weekly. Dependabot monitors Python and GitHub Actions
dependencies weekly. Repository workflows must never patch and push application code during
normal CI.

## Final boundary

AURA can be made software-production-ready in the repository, but real-money production
certification requires real broker credentials and elapsed forward market operation. That
external evidence cannot be manufactured by code or backtests. Until it exists, deploy
AURA as a production-grade **paper/demo research service**, not as an unrestricted live-money
system.
