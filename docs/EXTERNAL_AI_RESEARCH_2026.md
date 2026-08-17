# AURA AI OS — External AI / Agent / Live-Data Research, August 2026

This document records external systems studied for AURA and the specific ideas AURA should adopt or reject. The purpose is not to clone another trading bot. AURA remains a broker-agnostic, multi-market operating system with independent deterministic financial authority.

## 1. Nimbus-style multi-agent trading desk

A public Cloud9 Markets post described **NIMBUS** as a unified multi-agentic trading desk integrating different AI trading agents, with only one agent executing trades.

AURA adoption:

- preserve the unified trading-desk concept
- multiple analysts/forecasters/researchers may work concurrently
- only a narrow execution service may talk to broker adapters
- strengthen the pattern further: the execution service still cannot bypass AURA's independent deterministic RiskEngine
- all analysis, debate, risk flags, orders and fills remain replayable/auditable

AURA must not copy opaque or unverifiable performance claims from social media.

## 2. TradingAgents

Repository: `TauricResearch/TradingAgents` / active forks.

Useful ideas observed in the 2026 project:

- specialist analyst agents
- bull/bear research debate
- trader / portfolio-manager roles
- multiple LLM providers
- structured outputs
- checkpoint/resume
- persistent decision logs
- grounded sentiment/data-source contracts

AURA adoption:

- provider-neutral model registry/router
- adversarial deliberation before CEO synthesis
- structured typed AgentEvidence
- checkpointed/audited decisions
- model/provider diversity

AURA difference:

- AI risk-manager agents are advisory; independent deterministic financial risk remains authoritative
- no direct LLM-to-broker path
- live/backtest/paper share governed financial primitives

## 3. Microsoft RD-Agent(Q)

Repository: `microsoft/RD-Agent`.

RD-Agent(Q) automates quantitative R&D through iterative factor/model co-optimization and backtest feedback.

AURA adoption:

- autonomous hypothesis generation
- candidate strategy/factor versions
- measured feedback into the next research iteration
- bounded research budgets
- automatic backtest -> walk-forward -> Monte Carlo -> paper evaluation
- rejected candidates produce negative memory/feedback

AURA difference:

- an autonomous loop may reach `PAPER_VALIDATED`, but never final live `APPROVED`
- every candidate is immutable/versioned/content-hashed
- experiment dataset/config/execution assumptions are manifest-hashed

## 4. Microsoft Qlib

Repository: `microsoft/qlib`.

Useful capabilities:

- full quant research workflow
- data processing, model training and backtesting
- supervised ML / market-dynamics modeling / RL support
- online rolling models and concept-drift research
- factor/model benchmark ecosystem

AURA adoption direction:

- use Qlib-style research discipline and model comparison, not vendor performance numbers
- integrate tabular ML / sequence models behind AURA's research interfaces
- add drift-aware re-evaluation/retirement
- RL stays simulation/research-only until independently validated

## 5. FinRobot

Repository: `AI4Finance-Foundation/FinRobot`.

Useful ideas:

- lead orchestrator plus role-specific agents
- bull / bear / judge debate
- live data-provider failover
- deterministic financial computation separated from LLM narration
- provenance-linked research output

AURA adoption:

- deterministic calculations remain code, not LLM arithmetic
- LLMs explain, research, critique and synthesize
- adversarial bull/bear/counterfactual deliberation
- source/provenance tracking
- capability-based model selection

## 6. FinGPT

Repository: `AI4Finance-Foundation/FinGPT`.

Use case in AURA:

- optional finance-language specialist for sentiment/document/news research
- benchmark against general reasoning models inside AURA's own evaluation harness
- never assume a finance-specific LLM is more profitable merely because it is finance-tuned

## 7. FinMem

Repository: `pipiku915/FinMem-LLM-StockTrading`.

FinMem explores layered memory designed to resemble trader cognition.

AURA adoption:

- working memory for short-lived context
- episodic trade/regime memory
- semantic durable facts
- negative memory for failure modes
- incident memory for operational/risk events
- regime memory
- point-in-time retrieval so future outcomes cannot leak into historical decisions
- importance/trust/recency scoring and memory decay

## 8. AI-Trader live benchmark

Repository: `HKUDS/AI-Trader` and associated live-agent benchmark.

Key lesson: general LLM intelligence does not automatically translate into robust trading. Live evaluation reported large variation among models and emphasized risk-control capability as a major determinant of cross-market robustness.

AURA adoption:

- evaluate models by task inside AURA rather than choosing a single "smartest" LLM
- maintain a model performance registry by market/regime/task
- use shadow/paper live evaluation to update model reliability/calibration scores
- risk authority remains model-independent

## 9. Time-series foundation models

### Amazon Chronos-2

Repository: `amazon-science/chronos-forecasting`.

2025/2026 Chronos-2 supports zero-shot univariate, multivariate and covariate-informed forecasting. Chronos-Bolt variants provide faster/lighter forecasting.

### Google TimesFM 2.5

Repository: `google-research/timesfm`.

TimesFM 2.5 is a 200M-parameter time-series foundation model with long context, quantile forecasting and covariate support; 2026 repository updates include fine-tuning examples and agent-oriented tooling.

### Salesforce Moirai / Moirai-MoE

Repository: `SalesforceAIResearch/uni2ts`.

Moirai-MoE uses sparse mixture-of-experts time-series modeling. The Uni2TS repository also demonstrates an agent using a time-series foundation model as a tool.

AURA adoption:

- adapters for multiple forecast models
- standardized probabilistic `ForecastDistribution`
- quantile forecasts rather than only point direction
- ensemble weights based on AURA-measured reliability/calibration
- explicit disagreement metric
- no forecast model directly creates an order

## 10. Live data sources studied

### DhanHQ v2

Official Dhan live-market feed provides tick-by-tick WebSocket data across exchange segments. v2 documents JSON subscriptions and compact binary responses, with ticker, quote, OI, depth/full packet data. It supports multiple connections and thousands of subscribed instruments per connection.

AURA use:

- primary candidate for Indian NSE/BSE/MCX live market data/account execution where the user's account/API permissions support it
- decode into canonical LiveDataEvent / tick / candle / depth models
- sequence/reconnect/staleness supervision mandatory

### Binance

Official developer docs provide Spot/Futures/Options REST/WebSocket APIs, market-data WebSocket streams, testnet/demo environments, trade/kline/book/depth streams and connection/rate-limit semantics.

AURA use:

- crypto live market-data plane
- testnet/demo execution first
- local-order-book reconstruction must respect update sequence rules

### Kraken

AURA already contains a Kraken closed-candle WebSocket foundation; extend it to depth/trade/ticker sources where useful.

### FRED / ALFRED

Official St. Louis Fed APIs provide macro series and real-time/vintage semantics. ALFRED is particularly important for avoiding macro revision look-ahead bias.

AURA use:

- macro-event/series ingestion into KnowledgeFirewall
- store release/observation/vintage timestamps
- historical backtests use the vintage known at decision time

### SEC EDGAR

Official `data.sec.gov` APIs provide filings/submission history and XBRL company facts without API-key authentication.

AURA use:

- US fundamental/document evidence
- filing timestamp/provenance retained
- deterministic numerical extraction before LLM synthesis

## 11. AURA model hierarchy after this research

AURA should not run "all models on every tick". That would be slow, costly and likely less accurate. Use a cognitive router.

### Fast path

Runs continuously/near-continuously:

- deterministic market features
- data quality
- regime detection
- SMC/structure
- VWAP/volume/order-book
- execution-quality
- fast tabular/sequence classifiers

### Forecast path

Runs at configured candle/event boundaries:

- Chronos-2 adapter
- TimesFM 2.5 adapter
- Moirai/MoE adapter
- Qlib/custom ML candidates
- calibrated probabilistic ensemble

### Deep-reasoning path

Runs only when an opportunity/event merits the cost:

- strongest available reasoning LLM(s)
- finance-specific LLM where validated
- macro/news/fundamental research
- bull/bear/devil critique
- CEO synthesis

### Research path

Runs asynchronously from financial execution:

- RD-Agent-style hypothesis/factor/model discovery
- feature generation
- strategy variants
- walk-forward and Monte Carlo
- paper experiment management
- rejected-candidate learning

## 12. Human-like cognition target

"Human-like" in AURA means structured cognitive functions, not pretending an LLM has human consciousness:

1. Perceive — live multi-source data.
2. Orient — normalize, quality-check, identify regime.
3. Recall — point-in-time layered memory/RAG.
4. Forecast — heterogeneous probabilistic models.
5. Analyze — specialist agents in parallel.
6. Challenge — bull/bear/devil/counterfactual review.
7. Synthesize — CEO memo with uncertainty.
8. Gate — evidence-risk policy.
9. Decide financially — independent deterministic RiskEngine.
10. Execute — narrow broker adapter.
11. Observe outcome — ledger, fills, slippage, incidents.
12. Learn — research loop proposes new immutable candidates.
13. Validate — backtest, walk-forward, Monte Carlo, paper.
14. Promote/retire — governed lifecycle; final live approval remains human.

## 13. Accuracy objective

AURA must never claim a fixed 70–80% win rate as guaranteed. The engineering objective is stronger:

- maximize out-of-sample expected value after costs
- calibrate probabilities
- minimize severe drawdowns/tail failures
- maintain regime robustness
- measure win rate separately by market/timeframe/setup/regime
- reject models whose live-paper calibration degrades
- ensemble only when diversity improves OOS results
- compare AI methods against simple deterministic baselines

A model/agent is useful only if it adds statistically defensible incremental value after realistic costs and risk.

## 14. Explicit non-goals

- no LLM writes directly into live deployed strategy code
- no autonomous final live approval
- no strategy promotion from in-sample performance only
- no future/news/macro revision leakage
- no forced daily trade quota
- no hidden repainting of historical predictions
- no single social-media/repository claim is treated as proof of profitability
- no broker credentials in repository or agent prompts
