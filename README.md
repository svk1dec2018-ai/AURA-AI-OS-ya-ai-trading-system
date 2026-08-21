# AURA AI OS

AURA AI OS is a broker-agnostic, multi-market AI trading operating system. It combines deterministic financial controls, concurrent specialist agents, optional multiple AI models, strategy research/evolution, causal testing, paper/demo execution, durable accounting and fail-closed production governance in one system.

> **Current release class:** production-deployable **paper/demo research service candidate**. Real-money production remains intentionally gated by broker-origin forward evidence, immutable strategy approval and explicit human authorization.

See `docs/PRODUCTION_READINESS.md` for deployment and release procedures and `docs/IMPLEMENTATION_STATUS.md` for the current code-level status.

## Non-negotiable authority chain

```text
Point-in-time market/news/options data
              |
              v
Fast scanner / strategy research farm
              |
              v
Deterministic specialists + optional multiple AI models
              |
              v
Bull / Bear / Counterfactual deliberation
              |
              v
Reliability-weighted deterministic CEO synthesis
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

No AI model, CEO vote, research agent or strategy architect can bypass the independent risk/execution authority layers.

## Implemented highlights

### Financial core

- canonical candles, signals, orders, fills and portfolio snapshots
- broker-neutral instruments and symbol mapping
- shared strategy/agent -> RiskEngine -> order path
- position-aware reductions/closes vs new exposure
- kill switch, order-notional, gross-exposure, daily-loss and drawdown controls
- contract-aware accounting/exposure semantics
- deterministic order state machine
- idempotent fills and partial-fill VWAP
- cash/position ledger with fees and realized/unrealized P&L
- append-only checksum-protected financial WAL
- checkpoint + WAL-tail deterministic recovery
- broker/local reconciliation that freezes new risk on critical mismatch

### Multi-agent + multi-model intelligence

Core roles include:

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

The desk supports:

- concurrent specialist execution
- multiple local/provider AI agents through structured evidence
- Ollama multi-model council
- optional OpenAI Responses API council with strict structured output
- Bull/Bear/Counterfactual adversarial deliberation
- deterministic CEO synthesis
- market/regime/role-specific agent and model reliability learning
- adaptive model routing with controlled exploration
- counterfactual scoring of directional AI opinions even when the final trade is skipped
- bounded AI in-flight capacity so slow models do not stall market ingestion

Raw private model reasoning is not treated as trading evidence; AURA stores validated conclusions, confidence, factors, provenance and risk flags.

### Controlled maintenance and development AI

- free local Ollama or optional OpenAI system diagnosis and unified-diff repair proposals
- deterministic AI/developer/owner authority matrix
- tracked-file-only, credential-free patch sandbox with fixed test commands
- exact base-commit, patch-hash and owner-approval binding
- restart-safe proposal, validation, approval and application WAL
- development worktree apply and exact rollback without automatic commit/push/deploy
- append-only P&L/trade reporting corrections without rewriting fills or broker truth
- owner, developer and AI all hard-blocked from deposit, withdrawal, fund transfer, risk bypass and secret disclosure

See `docs/CONTROLLED_SELF_IMPROVEMENT.md` for commands and the complete authority contract.

### Autonomous strategy research

- bounded strategy DSL and factory
- safe mutation/crossover/population evolution
- live shadow strategy lab
- AI Strategy Architect for bounded component proposals
- causal blueprint compiler for supported primitives
- no AI-controlled leverage, order quantity, kill switch, risk limits or broker permissions
- causal next-bar execution backtesting
- multi-symbol shared-portfolio backtesting
- leakage-safe walk-forward testing
- block-bootstrap Monte Carlo robustness
- immutable experiment/research manifests
- research -> backtest -> robustness -> paper -> human approval lifecycle
- paper champion/challenger evolution
- missed-opportunity, wrong-direction and capture-rate learning
- restart-safe pending opportunity labels and deterministic online-learning replay

### Market data and broker/data adapters

Implemented foundations/adapters include:

- Exness / MetaTrader 5 DEMO data and guarded demo adapter
- Dhan Indian-market master, ticker, FULL depth/OI/volume, history and option-chain context
- Shoonya read-only live/historical data
- Flattrade read-only live/historical data
- OANDA v20 read-only/practice data
- Binance and Kraken foundations
- Coinbase, Bybit and OKX public/no-key crypto market-data adapters
- cross-feed price sanity/outlier guard
- second-level research candle aggregation

### Free/official intelligence

- point-in-time KnowledgeFirewall
- RBI/SEBI official-feed support
- GDELT
- optional FRED, SEC EDGAR and Alpha Vantage integrations
- contradiction handling and future-observation rejection

## Production operations

AURA now includes explicit production controls:

- `ProductionPreflight` for deployment mode, secrets/config and durable runtime checks
- `HealthReport` with HEALTHY / DEGRADED / UNHEALTHY readiness semantics
- `ProductionReleaseGate` for objective live-canary eligibility
- non-root Linux Docker image for public/HTTP/WebSocket services
- Windows/MT5 deployment guidance
- Python package build validation
- CodeQL and Dependabot
- non-self-modifying CI

Default live-canary release policy requires, at minimum:

- immutable strategy stage `APPROVED`
- evidence source exactly `LIVE_BROKER`
- at least 1,000 forward broker-origin trades
- at least 30 elapsed forward-live days
- positive expectancy
- profit factor >= 1.10
- max drawdown <= 10%
- zero critical incidents
- zero reconciliation failures
- zero unresolved data-integrity incidents
- explicit external human approval ID and live-risk acknowledgement

These are minimum engineering gates, not a guarantee of profitability.

## Quick start — development verification

Python 3.11+ is required; Python 3.12 is recommended.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m pip check
ruff check aura tests examples
pytest -q
python -m build
```

Production configuration smoke without broker credentials:

```bash
python examples/run_production_preflight.py --mode paper --connector public
```

## Run without broker credentials

Public crypto live-data path:

```bash
python examples/run_public_crypto_live.py
```

Autonomous strategy research farm:

```bash
python examples/run_free_public_strategy_lab.py
```

Local multi-AI council with Ollama:

```bash
# Five key-free local assistants: Qwen 3.5, DeepSeek-R1, Llama 3.1,
# Gemma 3 and Phi-4 Mini.
export AURA_FREE_AI_PRESET="balanced5"
export AURA_OLLAMA_KEEP_ALIVE="0"
export AURA_AI_OPINIONS_PER_ROLE="1"
aura-free-ai catalog
aura-free-ai probe
python examples/run_free_public_ai_council.py
```

The balanced preset uses local Ollama inference: no API key and no per-token provider
charge. The five downloads total approximately 20 GB, individual model licenses still
apply, and no claim is made that small local models match paid ChatGPT or Claude quality.
Requests are serialized and models unload after each request by default to limit RAM use.
An explicit `AURA_OLLAMA_MODELS` comma-separated list overrides the preset.

Owner-gated local maintenance developer:

```bash
export AURA_MAINTENANCE_AI_PROVIDER="ollama"
export AURA_MAINTENANCE_OLLAMA_MODEL="qwen3.5:4b"
aura-maintenance policy
aura-maintenance probe --repository .
```

Optional OpenAI advisory models and maintenance developer:

```bash
cp .env.example .env.local
# securely set OPENAI_API_KEY in .env.local
export AURA_OPENAI_MODELS="gpt-5.4-mini"
export AURA_MAINTENANCE_AI_PROVIDER="openai"
```

All AI models remain advisory inside the trading council. Maintenance patches go through
proposal -> credential-free sandbox -> tests -> exact owner approval -> development branch;
they never auto-merge or auto-deploy. Add/withdraw/transfer funds, historical ledger rewrites,
risk bypass, secret exposure and AI self-approval are unavailable to every provider and role.

Run the complete no-key autonomy stack (Multi-AI council + historical seed + live
intelligence + deterministic forecasts + missed-opportunity audit + forward-only
shadow strategy training):

```bash
python examples/run_free_public_autonomy.py --voice
```

On Windows, `START_AURA_OLLAMA.cmd` performs the preflight and starts this combined
runtime. It uses Coinbase/Bybit public market endpoints, GDELT and official feeds;
no third-party key is embedded. OS-native voice alerts are local and optional.

Run the same fail-closed stack continuously as a service:

```bash
# Docker Desktop / Docker Engine (voice disabled inside the container)
docker compose -f compose.paper.yml up -d --build
docker compose -f compose.paper.yml logs -f

# Linux systemd user service, after creating .venv and installing AURA
./scripts/install_aura_user_service.sh
systemctl --user status aura-paper.service
```

On Windows, first run `START_AURA_OLLAMA.cmd` successfully once, then register the
same launcher as a restartable logon task:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_aura_windows_task.ps1 -StartNow
```

These service modes explicitly clear live-trading authority and run the public
paper preflight before startup. See `docs/AURA_VISION_COVERAGE.md` for the exact
vision-to-code audit and `output/pdf/AURA_SETUP_AND_OPERATIONS.pdf` for the complete
operator guide.

Authorized books and video transcripts can be added through
`knowledge/public_corpus/manifest.jsonl`; see that directory's README. AURA never
downloads copyrighted books/transcripts automatically.

PowerShell uses `$env:NAME="value"` instead of `export`.

## Local mobile Command Center

```bash
export AURA_COMMAND_CENTER_OWNER_ID="owner"
export AURA_COMMAND_CENTER_TOKEN="use-at-least-32-random-characters"
python examples/run_command_center.py
```

Open `http://127.0.0.1:8765`. Read-only loopback status works without a token,
but research, development and financial-correction requests require authenticated owner access
and remain queued for governed review. Fund commands are rejected even for the owner. The browser
keeps the token in session storage only.

## Optional Telegram outbound alerts

Create a bot through Telegram's official BotFather flow, start a conversation with
that bot (or add it to the intended chat), then keep both values in the process
environment only:

```bash
export AURA_TELEGRAM_BOT_TOKEN="..."
export AURA_TELEGRAM_CHAT_ID="..."
python examples/send_telegram_test_alert.py
```

Successful and failed delivery receipts are checksummed and restart-safe at
`runtime/alerts/telegram_receipts.jsonl`. The journal contains only a hash of the
destination, never the token or raw chat ID. This adapter sends outbound alerts;
it does not accept commands and has no order-execution authority.

## MT5 / Exness demo + internal paper

On Windows with the MetaTrader 5 terminal installed:

```powershell
pip install MetaTrader5
$env:AURA_MT5_DEMO_LOGIN="..."
$env:AURA_MT5_DEMO_PASSWORD="..."
$env:AURA_MT5_DEMO_SERVER="..."

python examples/run_production_preflight.py --mode demo --connector mt5_demo
python examples/run_mt5_self_evolving_paper.py
```

AURA verifies DEMO account mode before guarded MT5 trading calls. The all-market self-evolution path remains paper/demo-first.

## Dhan live-data + internal paper

```powershell
$env:AURA_DHAN_CLIENT_ID="..."
$env:AURA_DHAN_ACCESS_TOKEN="..."

python examples/run_production_preflight.py --mode paper --connector dhan
python examples/run_dhan_self_evolving_paper.py
```

## Angel One SmartAPI read-only + reconciliation

AURA includes a concrete SmartAPI adapter for profile verification, LTP queries,
order/trade books, position snapshots, symbol routing and restart reconciliation.
Because SmartAPI order eligibility depends on the operator's current account and
static-IP requirements, submit/cancel remain deliberately locked until broker-origin
validation and the controlled-live phase gates pass.

Generate short-lived session tokens using Angel One's official login flow; AURA does
not accept or store your PIN/TOTP seed. Then run the account preflight:

```powershell
pip install smartapi-python
$env:AURA_ANGEL_ONE_API_KEY="..."
$env:AURA_ANGEL_ONE_CLIENT_CODE="..."
$env:AURA_ANGEL_ONE_JWT_TOKEN="..."
$env:AURA_ANGEL_ONE_REFRESH_TOKEN="..."
$env:AURA_ANGEL_ONE_FEED_TOKEN="..."  # optional for REST-only check

python examples/check_angel_one_account.py
```

The command prints only non-secret readiness/count information. It cannot place or
cancel an Angel One order.

## Docker

For public-data and HTTP/WebSocket services that do not require the Windows MT5 bridge:

```bash
docker build -t aura-ai-os .
docker run --rm -v aura-runtime:/app/runtime aura-ai-os
```

The Linux image does **not** claim MetaTrader 5 terminal support.

## Real-money boundary

AURA cannot be honestly certified for real-money production from code or backtests alone. Broker-specific credentials and elapsed forward operation are required to validate real fills, rejects, reconnects, margin mechanics, venue edge cases and operational stability.

When measured evidence exists, evaluate it with:

```bash
python examples/evaluate_production_release.py docs/production_release_evidence.example.json
```

The example file is a schema/example only. Do not substitute example values for real measured evidence.

Even a passing release manifest is insufficient without the existing human strategy approval plus explicit live-preflight authorization.

## Repository quality gates

Normal CI validates:

- Python 3.11 and 3.12
- dependency consistency
- compile smoke
- Ruff
- full pytest suite
- production public-paper preflight
- Python distribution build
- Docker production image build

CodeQL scans Python on push/PR and weekly. Dependabot monitors pip and GitHub Actions dependencies.

## Documentation

- `docs/PRODUCTION_READINESS.md` — deployment, canary and release runbook
- `docs/IMPLEMENTATION_STATUS.md` — current implemented/remaining status
- `docs/MULTI_AGENT_CONSTITUTION.md` — permanent AI/authority contract
- `docs/ARCHITECTURE.md` — architecture boundaries/invariants
- `docs/AURA_MASTER_BLUEPRINT_2026.md` — broader AURA blueprint
- `docs/DEMO_EVOLUTION_RUNBOOK.md` — paper/demo learning setup
- `SECURITY.md` — security boundaries

AURA is intentionally designed so research can move fast while live financial authority remains slow, explicit, auditable and fail closed.
