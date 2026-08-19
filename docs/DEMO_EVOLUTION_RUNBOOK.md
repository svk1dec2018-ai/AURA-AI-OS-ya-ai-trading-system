# AURA AI OS — Demo Evolution Runbook

This runbook is the supported path for the current AURA stage: **research + autonomous paper/demo validation only**. Real-money deployment is intentionally not enabled by the evolution workflow.

## 1. What is implemented now

AURA currently contains:

- broker-neutral market/order/risk domain models
- universal multi-venue instrument universe
- DhanHQ v2 market-feed and option-chain normalization
- Binance Spot/Testnet market-data normalization
- Kraken closed-candle ingestion foundation
- Exness/MetaTrader 5 dynamic symbol discovery contracts
- guarded MT5 DEMO connection and closed-candle history reader
- Dhan Sandbox order adapter
- fail-closed demo execution guard
- deterministic internal PaperBroker
- shared signal -> RiskEngine -> order path
- concurrent multi-agent scanner and central portfolio allocator
- WAL/recovery/reconciliation
- autonomous paper supervisor
- causal backtesting with fees and adverse slippage
- rolling walk-forward OOS evaluation
- block-bootstrap Monte Carlo robustness
- immutable strategy genomes
- bounded population evolution / champion-challenger research
- measured paper outcome tracker keyed by immutable genome hash
- paper champion checkpoint with `live_approved=false`
- model performance, drift and forecast ensemble foundations

The strategy evolution example included here evolves a reference EMA parameter family only to prove the governed learning machinery. It is **not** a profitability claim and is not the final AURA alpha stack. The production objective is to apply the same evaluator/governance contracts to validated multi-agent/feature/model candidate families.

## 2. Recommended machine for Exness MT5

Use a Windows 11 PC or Windows VPS that can run the MetaTrader 5 desktop terminal and Python 3.11/3.12. The official `MetaTrader5` Python integration communicates with the installed terminal, so the MT5-facing process belongs on that Windows host.

AURA's non-MT5 services can later be split across Linux/VPS workers, but start with one Windows demo machine to remove operational complexity.

## 3. Install

PowerShell:

```powershell
git clone https://github.com/svk1dec2018-ai/AURA-AI-OS-ya-ai-trading-system.git
cd AURA-AI-OS-ya-ai-trading-system
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pip install MetaTrader5
```

Run engineering checks:

```powershell
ruff check aura tests examples
pytest -q
```

## 4. Exness MT5 DEMO setup

1. Create/use an Exness **demo** MT5 account.
2. Install and launch MetaTrader 5.
3. Log the terminal into that demo account once and confirm symbols/ticks are visible.
4. Put credentials only in environment variables, never in GitHub or source files.

PowerShell:

```powershell
$env:AURA_MT5_DEMO_LOGIN="YOUR_DEMO_LOGIN"
$env:AURA_MT5_DEMO_PASSWORD="YOUR_DEMO_PASSWORD"
$env:AURA_MT5_DEMO_SERVER="YOUR_EXNESS_DEMO_SERVER"
```

If AURA cannot locate the terminal automatically:

```powershell
$env:AURA_MT5_TERMINAL_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"
```

The gateway reads `account_info()` and refuses trading calls unless the MT5 account is identified as DEMO. A real/contest account is rejected by `DemoExecutionGuard`.

## 5. Run the first real-data evolution experiment

Example XAUUSD 5-minute research run:

```powershell
python examples/run_mt5_demo_evolution.py --symbol XAUUSD --timeframe 5m --bars 5000 --population 8 --generations 8 --quantity 0.01 --slippage-bps 1.5
```

If Exness uses a broker suffix such as `XAUUSDm`, pass the exact symbol exposed by your MT5 account.

This command:

1. authenticates only to an MT5 DEMO account
2. dynamically discovers the account's tradable symbols
3. fetches only fully closed candles (`start_pos=1`, skipping the currently forming bar)
4. creates immutable candidate parameter genomes
5. evaluates each through AURA's shared DecisionPipeline and independent RiskEngine
6. uses next-bar execution with configured fees/slippage
7. evaluates rolling OOS windows
8. block-bootstraps OOS returns with Monte Carlo
9. ranks candidates under bounded population evolution
10. journals candidate results under `runtime/evolution/mt5_demo/`

Historical research alone cannot become a paper champion. The evaluator returns no paper evidence until actual paper/demo trade outcomes are attached through `PaperGenomePerformanceTracker`.

For a restart-safe paper validation run, construct that tracker with a dedicated
`journal_path` inside the run state directory. The resulting checksummed JSONL WAL
binds the configured starting equity and fsyncs each measured closed trade or
incident before updating in-memory metrics. Stable trade and incident IDs make
retries idempotent; collisions, sequence gaps, checksum failures and equity changes
fail closed.

Reconciliation and operational incidents are propagated by the tracker into
`CandidateEvaluation`. They therefore remain active inputs to the existing fitness
and paper-promotion firewall instead of being silently reduced to performance-only
metrics.

## 6. What the evolution files mean

`runtime/evolution/mt5_demo/evolution.jsonl`

- append-only candidate evaluations
- failure reasons
- generation and genome IDs
- fitness scores
- OOS trade counts
- paper promotion events when they eventually exist

`runtime/evolution/mt5_demo/paper_evidence.jsonl` (when configured)

- measured closed paper trades keyed by immutable genome hash and trade ID
- reconciliation and operational incidents with stable incident IDs
- version, sequence and checksum validation for deterministic restart replay

`runtime/evolution/mt5_demo/paper_champion.json`

- written only when the candidate passes both research and measured paper gates
- always stores `live_approved: false`
- does not enable a broker live-money route

Do not commit the runtime folder if it contains account-derived operational data.

## 7. Dhan Indian market sandbox

AURA's Dhan sandbox adapter is pinned to:

```text
https://sandbox.dhan.co/v2
```

Set sandbox credentials from the Dhan developer sandbox, not production credentials:

```powershell
$env:AURA_DHAN_SANDBOX_CLIENT_ID="YOUR_SANDBOX_CLIENT_ID"
$env:AURA_DHAN_SANDBOX_ACCESS_TOKEN="YOUR_SANDBOX_ACCESS_TOKEN"
```

`DhanSandboxBroker` maps each canonical AURA symbol to the Dhan `securityId`, `exchangeSegment` and product type, then normalizes sandbox trades back into AURA fills. Any attempt to replace the base URL with the production Dhan host is rejected by the demo guard.

The Indian data/intelligence scope remains:

- NSE/BSE cash equities and eligible ETFs
- NIFTY/BANKNIFTY and other supported index futures/options
- eligible single-stock futures/options
- MCX liquid commodities and supported derivatives
- contract-aware expiry/strike/CE/PE/OI/IV/Greeks/liquidity analysis

## 8. Binance/Kraken

AURA already contains Binance Spot/Testnet and Kraken market-data foundations. The demo guard allows Binance testnet hosts and rejects production execution hosts for demo workflows.

Crypto demo/testnet execution should remain a separate broker adapter behind the same AURA `BrokerAdapter`, `RiskEngine`, reconciliation and journal contracts.

## 9. Evolution rule — what AURA may change automatically

Allowed in research/demo:

- candidate strategy parameters
- candidate feature thresholds
- candidate model routing/weights
- candidate model selection
- candidate regime-specific configuration
- new immutable research hypotheses
- champion/challenger ranking
- rejection/demotion after deterioration

Not allowed automatically:

- modifying the approved live strategy in place
- changing RiskEngine authority
- disabling reconciliation
- exposing broker credentials to an AI model
- marking historical research as paper evidence
- marking paper success as human live approval
- switching a demo URL/account to production

## 10. Learning loop

```text
ALL ENABLED MARKET DATA
        |
        v
Data quality / PIT / regime context
        |
        v
10 specialist agents + forecast/model challengers
        |
        v
Bull / Bear / Counterfactual review
        |
        v
CEO synthesis
        |
        v
Independent RiskEngine
        |
        v
Paper / Demo execution
        |
        v
Fills + fees + slippage + incidents
        |
        v
Cognitive failure memory + performance tracker
        |
        v
Research hypothesis / immutable genomes
        |
        v
Backtest -> rolling OOS -> Monte Carlo
        |
        v
Challenger paper run
        |
        +---- fail ----> negative memory -> mutate/research again
        |
        +---- pass ----> PAPER CHAMPION (still NOT live-approved)
```

## 11. Before real money is even considered

Do not enable live money merely because a candidate wins one backtest or one week of demo trading. At minimum the project still needs sustained real-data paper operation across intended markets, reliable broker reconciliation, venue-specific fees/margin/contract rules, options/futures aggregate risk, data-source failure tests, operational monitoring, and sufficient sample sizes across regimes.

Final live eligibility remains a separate human-approved deployment stage after the evidence exists.

## 12. Useful commands

```powershell
# Full CI-equivalent local checks
ruff check aura tests examples
pytest -q

# XAUUSD research evolution
python examples/run_mt5_demo_evolution.py --symbol XAUUSD --timeframe 5m --bars 5000

# Faster smoke experiment (still >= 1000 bars)
python examples/run_mt5_demo_evolution.py --symbol XAUUSD --timeframe 15m --bars 1500 --population 4 --generations 3
```

## 13. Secrets

Never paste API keys/passwords into:

- Python files
- `.env` committed to Git
- GitHub issues
- screenshots
- AI prompts

Use environment variables or a secret manager on the machine actually running AURA.
