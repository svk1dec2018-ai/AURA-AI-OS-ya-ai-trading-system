# AURA AI OS — Runtime & Deployment Runbook

This runbook is for the current **live-data + internal-paper / guarded-demo** stage. Real-money activation is intentionally not part of these commands.

## 1. Recommended host

### Simplest all-in-one host

Use **Windows 11 Pro or Windows Server 2022/2025 VPS**, because the Exness/MT5 path uses MetaQuotes' `MetaTrader5` Python package and a locally installed/running MetaTrader 5 terminal.

Recommended baseline:

- 4+ CPU cores;
- 16 GB RAM minimum; 32 GB preferred when many symbols/models are enabled;
- 80+ GB SSD;
- stable wired/datacenter network;
- Python 3.11 or 3.12;
- Git;
- MetaTrader 5 terminal for the Exness DEMO account;
- Windows clock/timezone synchronization enabled.

A future distributed deployment may keep MT5 on a Windows worker and run research/data services on Linux, but that is more operationally complex than the current single-host setup.

## 2. Clone and install

PowerShell:

```powershell
git clone https://github.com/svk1dec2018-ai/AURA-AI-OS-ya-ai-trading-system.git
cd AURA-AI-OS-ya-ai-trading-system
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

On the Windows MT5 host also install MetaQuotes' Python bridge:

```powershell
pip install MetaTrader5
```

AURA lazy-loads this package only on the MT5 terminal host.

## 3. Validate before connecting anything

```powershell
ruff check aura tests examples
pytest -q
```

Do not add broker keys if this baseline is not green.

## 4. Secrets policy

Set secrets only on the runtime machine or a secret manager. Never put them in GitHub commits, strategy files, prompts, screenshots, logs or notebooks.

### Exness / MT5 DEMO

```powershell
$env:AURA_MT5_DEMO_LOGIN="12345678"
$env:AURA_MT5_DEMO_PASSWORD="..."
$env:AURA_MT5_DEMO_SERVER="Exness-MT5Trial..."
# Optional when auto-discovery cannot find the terminal:
$env:AURA_MT5_TERMINAL_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"
```

The MT5 gateway explicitly checks that the connected account is DEMO before guarded broker trading calls are permitted.

### Dhan live market data

```powershell
$env:AURA_DHAN_CLIENT_ID="..."
$env:AURA_DHAN_ACCESS_TOKEN="..."
```

Dhan's current official Data API is a paid data subscription; AURA does not mark it as a free feed.

### Shoonya / Finvasia market data

```powershell
$env:AURA_SHOONYA_USER_ID="..."
$env:AURA_SHOONYA_ACCOUNT_ID="..."
$env:AURA_SHOONYA_SESSION_TOKEN="..."
```

The current AURA Shoonya transport is data-first. It implements REST history/quotes and reconnecting WebSocket touchline ingestion; live broker order routing is not enabled by this adapter.

### Flattrade Pi v2 market data

```powershell
$env:AURA_FLATTRADE_USER_ID="..."
$env:AURA_FLATTRADE_ACCOUNT_ID="..."
$env:AURA_FLATTRADE_ACCESS_TOKEN="..."
```

AURA implements the current Pi v2 touchline WebSocket and TPSeries data path. Order routing remains disabled until broker-specific reconciliation and current static-IP/regulatory deployment rules are validated.

### OANDA v20 practice data

```powershell
$env:AURA_OANDA_ACCOUNT_ID="..."
$env:AURA_OANDA_ACCESS_TOKEN="..."
$env:AURA_OANDA_ENVIRONMENT="practice"
```

The current OANDA adapter is read-only pricing/candle data. Keep `practice` during validation.

### Optional intelligence keys

```powershell
$env:AURA_FRED_API_KEY="..."
$env:AURA_ALPHA_VANTAGE_API_KEY="..."
$env:AURA_SEC_USER_AGENT="AURA-AI-OS your-email@example.com"
```

RBI/SEBI official RSS and GDELT do not require these keys. FRED, Alpha Vantage and SEC are additional sources.

## 5. First recommended run — Exness/MT5 live data, internal paper

Start MT5 and log in to the Exness DEMO account first. Then:

```powershell
python examples/run_mt5_self_evolving_paper.py `
  --cash 10000 `
  --max-symbols 0 `
  --seed-bars 250 `
  --optimizer-min-samples 250 `
  --research-every-samples 100 `
  --forward-paper-trades 50
```

`--max-symbols 0` means no artificial symbol count cap in the runner. AURA still applies data/risk/execution eligibility and does not force a trade.

State is written under:

```text
runtime/mt5_self_evolving_paper/
```

Watch at minimum:

- `status.json`;
- `brain/status.json`;
- financial journal;
- agent audit journal;
- opportunity audit;
- online-learning state/research triggers.

## 6. Indian-market Dhan live-data paper run

After the Dhan Data API credentials are active:

```powershell
python examples/run_dhan_self_evolving_paper.py `
  --cash 300000 `
  --broad-cap 5000 `
  --deep-top 40 `
  --history-days 35 `
  --optimizer-min-samples 250 `
  --research-every-samples 100 `
  --forward-paper-trades 50
```

Current pipeline:

```text
Dhan broad Ticker universe
 -> deterministic radar
 -> dynamic shortlist
 -> Full volume/OI/depth/spread
 -> option-chain/IV/PCR/Greeks context where eligible
 -> official/free live intelligence cache
 -> 10-agent desk + adversarial deliberation
 -> CEO
 -> deterministic RiskEngine
 -> internal PaperBroker
 -> live outcome/missed-opportunity audit
 -> safe online measurement
 -> governed challenger research
```

State is written under:

```text
runtime/dhan_self_evolving_paper/
```

## 7. Free/low-cost redundant data paths

AURA now has concrete read-only data transports for Shoonya, Flattrade and OANDA in addition to its MT5/Dhan/Binance/Kraken foundations.

They are intended to become redundant/cross-check feeds through the cross-feed consensus guard. Do not assume symbol IDs are interchangeable across brokers. Each provider's instrument master/token mapping must be normalized into AURA's canonical instrument ID before cross-feed comparison.

## 8. What continuous learning means

AURA can update small online measurements on each meaningful feed/decision/fill/outcome event:

- calibration error;
- prediction error;
- captured/missed/wrong-direction rates;
- spread/slippage/latency;
- regime/drift statistics;
- memory salience.

This event loop does **not** rewrite a deployed strategy every millisecond. When enough evidence crosses a drift/failure threshold, it emits a research trigger into the governed challenger pipeline. That separation protects the live/paper system from unstable online overfitting.

## 9. Promotion stages

```text
RESEARCH
 -> CAUSAL BACKTEST
 -> WALK-FORWARD
 -> MONTE CARLO / ROBUSTNESS
 -> SEALED HOLDOUT
 -> NEW FORWARD LIVE-DATA SHADOW/PAPER
 -> PAPER CHAMPION
 -> BROKER-SPECIFIC CANARY / RECONCILIATION
 -> EXPLICIT HUMAN LIVE APPROVAL
```

Historical/replayed data alone cannot create a paper champion. A paper champion cannot automatically become live-approved.

## 10. Before any real-money activation

Do not enable real-money routing until all of these exist for the specific broker/account:

1. sustained forward live-data paper/demo evidence across multiple regimes;
2. positive net expectancy after fees/spread/slippage;
3. controlled drawdown and portfolio correlation exposure;
4. acceptable captured/missed/wrong-direction statistics;
5. broker contract/lot/tick/margin/freeze rules verified;
6. idempotent order-state and fill reconciliation verified under disconnect/restart;
7. stale-feed and cross-feed divergence handling tested;
8. kill switch, alerts and operator monitoring working;
9. current regulatory/static-IP requirements satisfied;
10. explicit human approval for the broker and strategy version.

## 11. What to send when connecting accounts

Do **not** paste secrets into source code. On the runtime machine, set the environment variables above. To diagnose connection setup, share only non-secret information such as:

- broker name;
- DEMO/paper/live account type;
- MT5 server name (without password);
- whether API/data subscription is active;
- error code/message with tokens redacted;
- OS/Python version.
