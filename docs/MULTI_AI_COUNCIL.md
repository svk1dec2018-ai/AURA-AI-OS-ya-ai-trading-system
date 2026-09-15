# AURA Multi-AI Council

AURA can augment its deterministic ten-specialist trading desk with multiple local reasoning models through Ollama.

## Safety boundary

The AI council is advisory only. AI models may independently analyze the market, disagree, abstain and propose directional evidence, but they cannot:

- call a broker;
- size a position;
- change RiskEngine limits;
- disable a kill switch;
- mutate live strategy code;
- approve a strategy for live money.

The authority chain remains:

```text
market data / news / options / cross-market context
 -> deterministic specialists + AI specialists in parallel
 -> adversarial bull/bear/counterfactual review
 -> deterministic CEO evidence synthesis
 -> agent safety policy
 -> independent RiskEngine
 -> internal paper/demo execution
```

## Why Ollama

AURA's current concrete AI adapter targets the local Ollama `/api/chat` interface and uses JSON-schema structured output. A model may use its internal thinking capability, but AURA deliberately discards raw thinking text and records only the validated decision, confidence, risk flags, concise factors and invalidation condition.

No broker credentials are needed to run the local AI council.

The combined public autonomy runtime also seeds point-in-time candles from the
official Coinbase Exchange or Bybit public REST endpoints, polls failure-isolated
official/GDELT intelligence, creates a conservative two-baseline probabilistic
forecast, audits missed opportunities, and feeds resolved labels into bounded
online measurements. These measurements can queue research; they cannot mutate or
deploy a live strategy.

## Balanced five-model free preset

AURA ships a curated `balanced5` preset of complementary Ollama models:

| Local model | Council emphasis | Approximate download |
|---|---|---:|
| `qwen3.5:4b` | General reasoning and code review | 3.4 GB |
| `deepseek-r1:8b` | Deliberate reasoning and counter-analysis | 5.2 GB |
| `llama3.1:8b` | Broad instruction following and synthesis | 4.9 GB |
| `gemma3:4b` | Compact multilingual analysis | 3.3 GB |
| `phi4-mini:3.8b` | Compact reasoning and numerical cross-checks | 2.5 GB |

These are local, key-free model families with no per-token provider charge. Hardware,
electricity and storage still have a cost; individual model terms apply. "ChatGPT/Claude-like"
means they fill a conversational reasoning role, not that small local models are claimed to
equal paid frontier-model quality.

The catalog is machine-readable:

```powershell
aura-free-ai catalog
aura-free-ai probe
```

`probe` talks only to the credential-free local Ollama `/api/tags` endpoint and prints exact
missing `ollama pull ...` commands. It never downloads a model, calls a cloud AI, connects to a
broker or changes trading authority.

## Configure one or more local models

After Ollama is installed and the desired local models have been pulled, configure AURA with environment variables.

PowerShell example:

```powershell
$env:AURA_FREE_AI_PRESET="balanced5"
$env:AURA_OLLAMA_URL="http://127.0.0.1:11434"
$env:AURA_OLLAMA_THINK="false"
$env:AURA_OLLAMA_TIMEOUT_SECONDS="120"
$env:AURA_OLLAMA_MAX_CONCURRENCY="1"
$env:AURA_OLLAMA_KEEP_ALIVE="0"
$env:AURA_AI_AGENT_TIMEOUT_SECONDS="240"
```

An explicit comma-separated `AURA_OLLAMA_MODELS` value overrides the preset. Set
`AURA_FREE_AI_PRESET=off` and leave `AURA_OLLAMA_MODELS` blank to disable local AI.

Thinking is disabled by default because only thinking-capable models (for example,
Qwen 3) accept it. AURA automatically retries an Ollama HTTP 400 once without
thinking and with broad JSON mode for mixed-model and older-server compatibility.
Local model requests are serialized by default to avoid RAM pressure and queue
timeouts. `AURA_OLLAMA_KEEP_ALIVE=0` unloads a model after each response so the five-model set
does not remain resident in RAM. This is the safest but slowest setting. Operators with measured
headroom can use a bounded duration such as `30s`; negative/keep-forever values are rejected.
Raise `AURA_OLLAMA_MAX_CONCURRENCY` only after measuring the machine.

Optional role selection:

```powershell
$env:AURA_AI_ROLES="htf_bias,smc_ict,technical,volume_vwap,forecast,options_volatility,macro_sentiment,cross_market,regime,execution_quality"
```

Optional multiple independent opinions per role:

```powershell
$env:AURA_AI_OPINIONS_PER_ROLE="2"
```

Allowed range is 1-3. More opinions substantially increase latency and compute cost.

## Automatic integration

`build_default_agent_team()` automatically detects the selected free preset or an explicit
`AURA_OLLAMA_MODELS` list. Therefore the existing Dhan and MT5/Exness paper/self-learning
runtimes gain AI council members without a separate trading code path. The governed strategy
architect inherits the same list unless `AURA_STRATEGY_ARCHITECT_MODELS` overrides it.

With no preset or explicit model list configured, AURA falls back to its deterministic
specialist desk and does not make model-server calls.

## What each AI receives

Only bounded point-in-time context is sent to the local model:

- recent closed OHLCV candles;
- decision timestamp;
- selected higher-timeframe context;
- current options snapshot when available;
- forecast ensemble when available;
- cross-market context when available;
- execution-quality context when available;
- timestamp-safe live intelligence when available.

Credentials, broker secrets and arbitrary runtime objects are not part of the AI prompt.

License-gated local knowledge chunks may also be supplied through
`knowledge/public_corpus/manifest.jsonl`. Only `.md`/`.txt` sources explicitly marked
public-domain, open-licensed, official-open or user-provided are eligible. Every
retrieved chunk carries source, timestamp, trust score and SHA-256 content hash.

## One-click autonomous research

On Windows run `START_AURA_OLLAMA.cmd`. It starts both the council and the public
forward-shadow strategy lab, with optional local SAPI voice alerts. On first run the launcher
pulls missing `balanced5` models (approximately 20 GB total); use the PowerShell
`-SkipModelPull` switch when downloads must be managed separately. Direct Python:

```powershell
python examples/run_free_public_autonomy.py --provider coinbase `
  --symbols BTC-USD ETH-USD --timeframe 5s --voice
```

Runtime audit state is written below `runtime/free_public_autonomy/`. Broker orders,
real-money execution and automatic research promotion remain disabled.

The council persists resolved opportunity labels in an append-only JSONL audit and
atomically checkpoints labels still waiting for their causal horizon. On restart,
duplicate closed bars cannot advance a horizon twice, unresolved labels resume, and
the safe online-learning EWMAs are deterministically rebuilt from the resolved audit.
Checkpoint policy changes fail closed while unresolved labels exist. This recovery
restores research measurements only; it grants no strategy, risk or broker authority.

## AI mandates

AURA can create independent AI specialists for:

- higher-timeframe bias;
- SMC/ICT structure;
- technical reasoning;
- volume/VWAP;
- forecast interpretation;
- options/volatility;
- macro/news/sentiment;
- cross-market confirmation;
- regime classification;
- execution quality.

Each specialist must choose LONG, SHORT or FLAT with confidence and concise evidence. FLAT is required when evidence is insufficient or contradictory.

## Running with the existing paper systems

MT5/Exness demo live-data paper:

```powershell
python examples/run_mt5_self_evolving_paper.py
```

Dhan live-data internal paper:

```powershell
python examples/run_dhan_self_evolving_paper.py
```

When the Ollama environment variables are present, the AI specialists automatically join the same agent team used by those runtimes.

## Local repair proposals

The same local Ollama installation can power `aura-maintenance propose`. Its source excerpts are
redacted and its output is a strict repair-plan schema. The model cannot write files or run its
own commands: AURA validates the proposed unified diff in a credential-free sandbox, binds it to
an exact hash, and requires separate owner approval before applying it to a clean development
worktree. See `docs/CONTROLLED_SELF_IMPROVEMENT.md`.

## Performance note

The fast broad scanner should remain deterministic. Deep AI reasoning should run on shortlisted/high-value contexts because local reasoning models are much slower than tick ingestion. This preserves market coverage while still using richer AI thinking on decisions that matter.
