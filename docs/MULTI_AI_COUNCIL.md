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

## Configure one or more local models

After Ollama is installed and the desired local models have been pulled, configure AURA with environment variables.

PowerShell example:

```powershell
$env:AURA_OLLAMA_MODELS="model-a,model-b"
$env:AURA_OLLAMA_URL="http://127.0.0.1:11434"
$env:AURA_OLLAMA_THINK="false"
$env:AURA_OLLAMA_TIMEOUT_SECONDS="120"
$env:AURA_OLLAMA_MAX_CONCURRENCY="1"
$env:AURA_AI_AGENT_TIMEOUT_SECONDS="240"
```

Use actual model names installed in Ollama. Multiple models can be listed comma-separated.

Thinking is disabled by default because only thinking-capable models (for example,
Qwen 3) accept it. AURA automatically retries an Ollama HTTP 400 once without
thinking and with broad JSON mode for mixed-model and older-server compatibility.
Local model requests are serialized by default to avoid RAM pressure and queue
timeouts; raise `AURA_OLLAMA_MAX_CONCURRENCY` only after measuring the machine.

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

`build_default_agent_team()` automatically detects `AURA_OLLAMA_MODELS`. Therefore the existing Dhan and MT5/Exness paper/self-learning runtimes gain AI council members without a separate trading code path.

With no `AURA_OLLAMA_MODELS` configured, AURA falls back to its deterministic specialist desk and does not make network calls to a model server.

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

## Performance note

The fast broad scanner should remain deterministic. Deep AI reasoning should run on shortlisted/high-value contexts because local reasoning models are much slower than tick ingestion. This preserves market coverage while still using richer AI thinking on decisions that matter.
