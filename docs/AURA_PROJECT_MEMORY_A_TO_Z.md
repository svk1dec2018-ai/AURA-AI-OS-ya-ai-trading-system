# AURA AI OS — PROJECT MEMORY A→Z

> **Purpose:** Permanent continuity memory for every AI, developer, reviewer, or future session that continues AURA.
>
> **Canonical rule:** Read this file before making material AURA changes. Then inspect the actual code, tests, Git history, and current status documents. This file is a project-memory layer; the repository and executable evidence remain the final authority for what is actually implemented.
>
> **Last reconstructed:** 2026-09-08
>
> **Repository:** `svk1dec2018-ai/AURA-AI-OS-ya-ai-trading-system`
>
> **Default branch:** `main`
>
> **Current known release class:** production-deployable paper/demo research service candidate; unrestricted real-money production is intentionally gated.

---

## 0. IMPORTANT MEMORY SCOPE

This document reconstructs AURA's project memory from:

1. the retained AURA-related ChatGPT project context available to the current assistant,
2. AURA documents saved in the project/library,
3. the current GitHub repository source tree and its commit history,
4. the current `README.md`, `docs/IMPLEMENTATION_STATUS.md`, and `docs/PRODUCTION_READINESS.md`,
5. the historical AURA setup/master-prompt material.

This is **not a literal export of every ChatGPT message ever sent**. ChatGPT does not provide this project file a magic API containing every historical conversation message. Where exact historical wording or a vanished experiment is unavailable, do not invent it. Mark it as `UNKNOWN`, `RECONSTRUCTED`, or `NEEDS VERIFICATION`.

The Git history is authoritative for code changes. This file is authoritative for project intent, decisions, continuity rules, and known history that is not directly encoded in commits.

---

# A. AURA's MAIN GOAL — NEVER LOSE THIS

AURA is intended to become a **continuously observing, multi-market, broker-agnostic AI trading research and execution operating system** that behaves like a governed cognitive system rather than a simple trading bot.

The end state is a system that can:

- continuously observe market, order-flow, options, macro, news, fundamental, broker, and system information;
- normalize information with point-in-time correctness and provenance;
- rank attention so expensive reasoning is used where it matters;
- maintain world-state, working memory, episodic memory, semantic knowledge, and negative memory;
- run deterministic specialist analyses plus optional multiple AI models;
- debate Bull / Bear / Counterfactual views;
- synthesize through a reliability-weighted deterministic CEO layer;
- abstain when evidence is weak or uncertainty is high;
- pass every financial action through an independent RiskEngine;
- create bounded strategy candidates rather than unrestricted executable code;
- backtest without decision-time leakage;
- perform walk-forward, robustness, Monte Carlo, falsification, and holdout validation;
- paper/demo trade candidates and observe real execution friction;
- learn from trades, missed trades, errors, model reliability, regimes, and failures;
- retire weak strategies and remember why they failed;
- use champion/challenger governance;
- gradually promote only strategies that survive real evidence;
- eventually support a tiny, controlled, human-supervised live canary;
- never bypass safety, governance, compliance, rollback, or risk authority.

**The goal is not AGI and not guaranteed alpha.** The goal is governed, evidence-driven trading intelligence and execution.

---

# B. CONSTITUTION — PERMANENT DESIGN FILTER

These are the non-negotiable principles that must survive future AI handoffs.

1. AURA is an operating system for trading intelligence, not one strategy and not a chat-controlled buy/sell bot.
2. AURA is multi-market and broker-agnostic; instruments are normalized behind adapters.
3. Continuous scanning is allowed, but trading occurs only when net edge survives uncertainty, costs, liquidity, and risk constraints.
4. Technical analysis, price action, SMC/ICT, volume, VWAP, order-flow, options, macro, fundamentals, sentiment and cross-market signals are empirical hypotheses, not beliefs.
5. Specialist agents produce structured evidence. A CEO layer synthesizes. The independent risk layer has unconditional veto power.
6. Scalping, intraday, swing and positional behavior must use appropriate latency, feature, execution, and risk policies.
7. Every strategy follows: research → hypothesis → specification → realistic backtest → walk-forward → robustness → paper/demo → evaluation → approval/rejection.
8. No AI directly changes a live strategy. AI proposes bounded changes in a sandbox; the candidate is tested, versioned, approved, and reversible.
9. Learning must have provenance and time awareness.
10. Explainability, journaling, portfolio intelligence, observability, reconciliation, security, versioning and rollback are core capabilities.
11. Open-source / free tools are preferred for research and early paper work, but reliability is more important than ideological zero-cost purity.
12. Capital protection, reproducibility and risk-adjusted robustness outrank trade count, headline win rate and pretty backtests.

**Authority chain:**

```text
Point-in-time data
  -> attention/scanner
  -> deterministic specialists + optional AI
  -> Bull/Bear/Counterfactual
  -> reliability-weighted CEO
  -> evidence policy
  -> independent RiskEngine
  -> order state machine
  -> Paper/Demo/Broker adapter
  -> fill
  -> ledger/WAL/reconciliation
  -> outcome + missed-trade + reliability + evolution learning
```

No LLM, agent vote, CEO memo, strategy architect, or research loop may bypass downstream authority layers.

---

# C. EARLY PROJECT CONSTRAINTS VS CURRENT END-STATE

AURA evolved substantially. Future AIs must distinguish historical MVP constraints from the present architecture.

### Early / MVP-style constraints used during initial experimentation

- Python-first / Python-only implementation was strongly preferred.
- Free data sources were preferred.
- One market / one timeframe / at most a small number of strategies were used to keep experiments controlled.
- No live trading.
- Focus on research, backtesting, and paper operation.
- Risk and survival were prioritized over returns.

### Current architecture / end-state

AURA is intentionally **multi-market and broker-agnostic**, with adapters and normalization designed for Indian markets, MCX, forex, crypto, commodities and other future venues. The current repository contains multiple connectors and multi-market concepts.

Therefore: **do not mistake an early narrow experimental constraint for a permanent product limitation.** Narrow vertical slices are still preferred for validation and first live canary, but the product goal is broader.

---

# D. PROJECT EVOLUTION — HIGH-LEVEL CHATGPT HISTORY RECONSTRUCTION

The exact start date of the first AURA conversation is not preserved in one canonical transcript file. The evolution visible from retained project context is:

### Stage 1 — Original vision

The project started as the idea of an “AURA AI OS”: a self-evolving, broker-agnostic AI trading system inspired by institutional platforms and human cognitive systems.

The aspiration was larger than a strategy bot: market perception + multiple specialist brains + memory + CEO decision layer + risk authority + strategy discovery + learning + execution.

### Stage 2 — Strategy and market experimentation

Early work explored assets such as XAU/USD / Gold, Natural Gas, Crude Oil, NIFTY/BANKNIFTY, MCX, EURUSD, BTC and other crypto instruments. Experimental timeframes included 1m, 5m, 15m and 1h.

Historical data experiments included providers such as `yfinance` for Gold futures (`GC=F`), exchange/public crypto feeds, and other broker/public data paths.

Strategies encountered in experiments included trend pullback, volatility breakout, EMA-style strategies and mean reversion.

### Stage 3 — Multi-agent / institutional architecture

The architecture expanded into agents, data pipelines, strategies, execution, portfolio, risk, monitoring, learning, knowledge, and later a cleaner `aura/` package layout.

The intended cognitive structure became:

- perception / market data;
- attention / scanner;
- world model / regimes and relationships;
- working memory;
- episodic memory;
- semantic memory;
- negative memory;
- reasoning / specialist agents;
- executive CEO synthesis;
- independent risk/execution authority;
- reflection / post-mortem;
- controlled evolution.

### Stage 4 — Failure-driven engineering

During earlier experiments, AURA hit real implementation issues including:

- `KeyError` problems,
- `AttributeError` problems,
- `ValueError` in ML training when a training split had only one class,
- Pandas / MultiIndex shape and schema issues,
- model/runtime capacity issues,
- Ollama compatibility / queue-pressure issues,
- data-model incompatibilities between versions of the project.

A historically important lesson emerged: **never trust a module because an AI says it exists. Inspect imports, contracts, tests, and actual runtime behavior.**

One old AURA artifact also recorded that a prior uploaded V6 package was missing a real `NormalizedCandle` model and a minimal compatible version had to be reconstructed. This is a permanent warning against relying on incomplete zip snapshots.

### Stage 5 — Testing and validation mindset

Experiments moved from “does the backtest make money?” toward:

- costs and slippage;
- realistic execution;
- walk-forward testing;
- Monte Carlo robustness;
- causal next-bar execution;
- leakage controls;
- immutable experiment manifests;
- source provenance;
- evidence-based promotion.

An old project experiment included deep cross-verification across RELIANCE, NIFTY 50 and Gold for 2020–2024, but this is not by itself considered institutional proof. Such experiments are useful validation artifacts, not permission to trade real money.

### Stage 6 — AI council and adaptive reliability

AURA evolved from individual AI opinions to a structured multi-model / multi-agent council.

The design became:

- local Ollama models when useful;
- multiple specialist roles;
- structured `AgentEvidence` rather than trusting free-form model prose;
- Bull / Bear / Counterfactual deliberation;
- deterministic CEO synthesis;
- agent/model reliability learned by role, market and regime;
- adaptive model routing with controlled exploration;
- learning from skipped and dissenting opinions as well as executed trades.

This is reflected heavily in the Git history in August 2026.

### Stage 7 — Strategy evolution

The strategy factory became governed rather than free-form:

- immutable strategy genomes;
- bounded mutation / crossover / population evolution;
- strategy DSL;
- AI strategy architect;
- causal blueprint compiler;
- champion / challenger process;
- shadow strategy lab;
- paper evolution;
- no AI control over leverage, quantity, kill switch, risk limits, or broker permissions.

### Stage 8 — Production paper/demo hardening

AURA gained explicit production operations:

- fail-closed `ProductionPreflight`;
- `HealthReport` with HEALTHY / DEGRADED / UNHEALTHY;
- `ProductionReleaseGate`;
- non-root Docker target;
- CodeQL;
- Dependabot;
- deployment/runbook documentation;
- explicit human approval requirements;
- strict live-evidence boundary.

### Stage 9 — Autonomous public intelligence + shadow learning

The latest known GitHub commit before this memory update was:

`aeb3ebba7c57088a92a584079fda0c60b9d5eddc`

Message: **Add autonomous public intelligence and shadow learning (#9)**

The commit message reports 289 passing tests, full Ruff checks and a successful package build.

It added/expanded the no-key public autonomy stack, public historical intelligence, knowledge context, shadow learning and combined runtime documentation.

---

# E. CURRENT GITHUB REALITY — VERIFIED 2026-09-08

Repository:

`svk1dec2018-ai/AURA-AI-OS-ya-ai-trading-system`

Current known GitHub state:

- public repository;
- default branch `main`;
- active, not archived;
- code organized under the `aura/` package;
- major domains include agents, backtest, connectors, core, data, domain, evolution, execution, forecast, interface, knowledge, markets, etc.;
- root includes `.env.example`, Dockerfile, README, SECURITY, Ollama launcher, examples and tests.

The current implementation-status document explicitly classifies the system as a **production-deployable paper/demo research service candidate**, not unrestricted real-money production.

---

# F. CURRENT IMPLEMENTED CAPABILITIES — SOURCE-OF-TRUTH SUMMARY

The latest repository status describes these areas as implemented and wired.

## Financial / execution core

- canonical candles, orders, fills, portfolio snapshots;
- broker-neutral instruments and symbol mapping;
- signal → independent RiskEngine → order path;
- position-aware reductions / closes versus new exposure;
- kill switch;
- order-notional limits;
- gross-exposure limits;
- daily-loss and drawdown controls;
- contract-aware accounting / exposure;
- deterministic order state machine;
- idempotent fills;
- partial-fill VWAP;
- overfill rejection;
- cash / position ledger;
- fees and realized/unrealized P&L;
- long/short flips;
- deterministic PaperBroker with market / limit / stop simulation.

## Durable state / recovery

- checksum-protected append-only financial WAL;
- event/correlation IDs;
- monotonic sequencing;
- typed financial event journal;
- atomic checkpoints + WAL-tail replay;
- duplicate-fill-safe deterministic recovery;
- broker/local order and position reconciliation;
- critical divergence freezes new risk;
- connector circuit breaker;
- idempotency-aware retry guard.

## Market-data safety

- duplicate/out-of-order/gap/stale/future-data gates;
- session-aware candle aggregation;
- second-level research bars;
- cross-feed price sanity / outlier guard;
- Kraken/Binance foundations;
- Coinbase/Bybit/OKX public no-key live data;
- Exness/MT5 DEMO data and guarded demo execution;
- Dhan market master, ticker, FULL depth/OI/volume, history, option-chain/context;
- Shoonya read-only live/historical;
- Flattrade read-only live/historical;
- OANDA v20 practice/live read-only market data.

## Multi-agent / multi-model intelligence

Core roles documented in the current implementation include:

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

Implemented AI infrastructure includes concurrent specialist orchestration, structured point-in-time evidence, Ollama council support, Bull/Bear/Counterfactual deliberation, deterministic CEO synthesis, AgentRiskPolicy, contextual reliability learning, adaptive routing and counterfactual scoring.

## Specialist intelligence

- EMA / RSI / MACD / Bollinger / Keltner;
- liquidity sweep, BOS/CHoCH and FVG primitives;
- VWAP / relative volume / OBV / VPT;
- HTF context / trend-chop regime;
- Dhan option-chain PCR/IV/Greeks/liquidity context;
- spread/slippage/top-book checks;
- cross-market context;
- trusted macro/news via KnowledgeFirewall;
- explicit refusal to fabricate unsupported dealer positioning or options evidence.

## Knowledge / information plane

- point-in-time source / trust model;
- RBI / SEBI official-feed support;
- GDELT;
- optional FRED, SEC EDGAR, Alpha Vantage;
- timestamped intelligence cache;
- future-observed knowledge rejected;
- contradictory trusted claims fail closed.

## Research / evolution

- immutable strategy genomes;
- bounded DSL/factory;
- mutation/crossover/population evolution;
- live shadow strategy lab;
- AI Strategy Architect;
- bounded blueprint compiler;
- causal event-driven backtesting;
- next-bar semantics;
- multi-symbol shared portfolio backtesting;
- leakage-safe walk-forward;
- block-bootstrap Monte Carlo robustness;
- immutable research manifests;
- research → backtest → robustness → paper → human approval;
- paper/demo champion-challenger evolution;
- forward-only outcome labeling;
- missed-opportunity / wrong-direction / capture-rate learning.

## Live/paper runtimes

The repository documents:

- public no-key crypto live-data runner;
- public no-key autonomous strategy lab;
- public multi-AI council;
- MT5 all-market internal-paper path;
- MT5 self-evolving paper;
- Dhan Indian-market self-evolving paper;
- broad radar → deep shortlist architecture;
- bounded AI in-flight capacity to avoid blocking market ingestion.

---

# G. PRODUCTION BOUNDARY — DO NOT CROSS

AURA is **not certified for unrestricted real-money production** merely because code exists or tests pass.

The current release policy requires, at minimum:

- an immutable strategy in `APPROVED` stage;
- broker-origin forward evidence;
- at least 1,000 forward broker trades;
- at least 30 elapsed forward-live days;
- positive expectancy;
- profit factor ≥ 1.10;
- maximum drawdown ≤ 10%;
- zero critical incidents;
- zero reconciliation failures;
- zero unresolved data-integrity incidents;
- explicit external human approval/change ID;
- exact live-risk acknowledgement;
- smallest-size canary first;
- separate approval for scaling scope or capital.

Historical, synthetic, backtest, or public-data-only evidence must not be represented as broker-forward live proof.

These are engineering gates, **not a promise of profitability**.

---

# H. PAPER / DEMO OPERATING RULE

Recommended safe progression:

```text
Public no-key data
   ↓
Public shadow research
   ↓
Strategy Lab
   ↓
Multi-AI Council
   ↓
MT5 / Exness DEMO or Dhan live-data + internal paper
   ↓
Forward broker-origin paper/demo evidence
   ↓
Scientific evaluation
   ↓
Human approval
   ↓
Tiny live canary (future, conditional)
```

Never silently turn a demo runner into a live runner.

Never put passwords, API keys, tokens, TOTP seeds, approval IDs, or live credentials into GitHub, prompts, screenshots, notebooks, or chat.

---

# I. MEMORY ARCHITECTURE — HOW AURA ITSELF SHOULD REMEMBER

AURA's own cognitive memory must remain separated into layers.

## Working memory

Only current decision context:
- current instruments;
- recent events;
- active risks;
- current hypotheses;
- agent disagreement;
- open positions;
- immediate execution state.

## Episodic memory

Complete decision episodes:
- what AURA knew at the time;
- source timestamps;
- data versions;
- model/agent outputs;
- decision;
- action or abstention;
- execution;
- outcome;
- credible attribution.

## Semantic memory

Validated reusable knowledge:
- market mechanics;
- definitions;
- verified strategy facts;
- rules;
- research findings;
- source-linked concepts.

## Negative memory

Explicitly record:
- rejected hypotheses;
- failed strategies;
- stale or poisoned data episodes;
- leakage discoveries;
- operational failures;
- bad model regimes;
- repeated implementation mistakes;
- retired strategies;
- reasons for rejection.

The purpose is to prevent rediscovery of known bad ideas.

---

# J. STRATEGY FACTORY MEMORY

AURA should generate **strategy specifications / bounded blueprints**, not unrestricted deployable code.

A strategy specification should define:

- universe;
- data dependencies;
- feature definitions;
- decision horizon;
- state;
- entry conditions;
- exit conditions;
- sizing policy;
- risk limits;
- execution policy;
- expected regimes;
- invalidation criteria;
- testing plan.

The deterministic compiler produces executable behavior only through approved primitives.

Candidate generation may include:

- human hypotheses;
- LLM research extraction;
- symbolic regression / genetic programming within approved operators;
- alpha mining with complexity penalties;
- bounded Bayesian optimization;
- MCTS / evolutionary search;
- failure-driven edits;
- regime-specialized candidates;
- ensemble construction based on incremental portfolio value.

Promotion must use champion/challenger governance. The champion remains available for rollback.

---

# K. SCIENTIFIC VALIDATION RULES

AURA must assume that a profitable-looking backtest can be wrong.

Required thinking:

- point-in-time data;
- publication timestamps;
- no future information;
- next actually tradable price;
- spread / fees / slippage;
- latency;
- rejection;
- partial fills;
- queue / market impact assumptions;
- multiple-testing controls;
- complexity penalties;
- sealed holdout;
- walk-forward;
- regime coverage;
- robustness / bootstrap;
- out-of-distribution monitoring;
- calibration;
- reproducibility.

Every meaningful result should be traceable to:

`data version + code commit + environment + model version + prompt/spec + random seed + cost model + configuration`

---

# L. RISK ENGINE RULES

The independent RiskEngine is a constitutional authority, not another opinion agent.

It must consider:

- instrument permissions;
- price sanity;
- liquidity;
- order value;
- concentration;
- leverage;
- margin;
- options Greeks;
- scenario loss;
- broker/regulatory limits;
- quote freshness;
- duplicate/idempotency;
- rate limits;
- slippage budget;
- position races;
- broker connectivity;
- P&L;
- residual exposure;
- factor / asset / sector / currency exposure;
- correlation;
- volatility;
- drawdown;
- VaR/CVaR and stress;
- OOD / calibration / data drift;
- operational health;
- stale feeds;
- storage failures;
- credential anomalies;
- recovery readiness.

**Never convert an LLM sentence such as “90% confident” directly into position size.**

---

# M. EXECUTION BRAIN

Research and execution must share compatible order semantics.

Execution decisions can incorporate:

- market / limit / stop;
- urgency;
- slicing;
- venue/broker;
- spread;
- depth;
- volatility;
- order size;
- alpha decay.

Any RL or learning-based execution optimizer belongs in a high-fidelity simulator first. Production actions remain bounded by deterministic controls.

---

# N. CURRENT PHASE ROADMAP

The formal roadmap has 15 stages numbered 0–14.

### Phase 0 — Constitution & governance
Freeze mission, interfaces, forbidden actions, evidence and promotion policy.

### Phase 1 — Cloud workspace & reproducibility
Private GitHub source of truth, devcontainer, locked dependencies, CI, one-command setup, secrets template.

### Phase 2 — Point-in-time data platform
Normalized data, raw/clean layers, timestamps, quality, replay, lineage.

### Phase 3 — Deterministic backtest/live parity
Unified event/order state machine, costs, partial fills, latency, reconciliation.

### Phase 4 — Universal scanner & regime map
Universe, attention ranking, MTF features, liquidity, probabilistic regimes.

### Phase 5 — Baseline strategy library
Interpretable baseline strategies with strategy cards, assumptions, costs and OOS evidence.

### Phase 6 — Knowledge + cognitive memory
RAG, temporal graph, trust, working/episodic/semantic/negative memory.

### Phase 7 — Multi-agent decision + abstention
Specialists, debate, CEO schema, calibration and no-trade behavior.

### Phase 8 — Scientific validation laboratory
Walk-forward, purged/CPCV, Monte Carlo, multiple testing, falsification, reporting.

### Phase 9 — Strategy factory + typed DSL
Bounded generation, compiler, static verifier, novelty/redundancy, champion/challenger.

### Phase 10 — Shadow + broker paper trading
Real-time flow, paper orders, operations tests, reconciliation, incident drills.

### Phase 11 — Portfolio/risk/execution hardening
Cross-strategy capital, options/Greeks, stress, model risk, execution optimization.

### Phase 12 — Controlled self-evolution
Failure diagnosis, bounded edits, offline retraining, retirement, rollback.

### Phase 13 — Security/compliance/disaster recovery
Static IP, broker approvals, RBAC, secrets, signed builds, backups, restore.

### Phase 14 — Canary live + scaling
Tiny capital, one market/strategy/account slice, manual oversight, gradual evidence-based scaling.

**Current formal focus:** Phase 2 / data truth and reproducibility, while many later capabilities already exist in code as prototypes or wired components. This is intentional: later features do not compensate for untrusted data.

---

# O. WHY PHASE 2 REMAINS CRITICAL

The single most important unresolved engineering problem is proving that AURA can replay exactly what it knew at decision time.

Phase-2 evidence should establish:

- reproducible cloud workspace;
- versioned raw/clean schema;
- UTC-normalized timestamps with venue/session metadata;
- deterministic replay of identical event order;
- replay checksum;
- gap and anomaly visibility;
- safe duplicate/out-of-order handling;
- at least one live stream with safe reconnect;
- no future information leaking into features;
- lineage from raw event → derived bar/feature → decision;
- a committed Phase-2 evidence dossier.

**Do not add more AI agents merely to make the dashboard look smarter while this evidence remains weak.**

---

# P. OLD AURA PROJECT STRUCTURES THAT MAY APPEAR IN HISTORY

Historical AURA experiments used structures such as:

```text
v4_institutional_core/
  agents/
  data_pipeline/
  knowledge_engine/
  strategies/
  execution/
  portfolio/
  risk/
  learning/
  monitoring/
```

The current repository uses the newer `aura/` package layout. When historical references appear, map them to current code before editing.

An old master prompt also emphasized:

- architecture first;
- Clean Architecture / SOLID / DI;
- strict typing;
- Pydantic for critical models;
- async-first behavior where justified;
- specific exception handling;
- structured logging;
- stateless agents with persistent state outside agents;
- environment-based secrets;
- numerical correctness;
- pytest for agents and strategies;
- backtests with slippage and commission;
- survivorship-bias checks;
- RiskEngine before BUY;
- retry/backoff for LLM APIs.

These principles remain useful unless they conflict with the current repository architecture.

---

# Q. COMMON ERROR LESSONS — KEEP THEM FOREVER

### Lesson 1 — “It exists” is not proof

AI-generated code may create a class, module, test, or status file without correct wiring. Verify imports, call paths, behavior and tests.

### Lesson 2 — A passing test suite is not trading proof

Tests can prove software behavior for tested cases. They cannot prove profitability or real-broker robustness.

### Lesson 3 — Public data is not broker evidence

Public market streams can validate ingestion and shadow learning, but they do not prove actual broker fills, rejection behavior, latency, account state or slippage.

### Lesson 4 — Backtest success can be a trap

Leakage, overfitting, multiple-testing, unrealistic fills, survivorship bias and future information can make a strategy look much better than it is.

### Lesson 5 — Slow AI must never block market ingestion

Bound AI concurrency, timeouts, and failure isolation are mandatory.

### Lesson 6 — Missing data models cause version chaos

Never merge an incompatible reconstructed model just because it satisfies one importer. Compare the actual domain contracts first.

### Lesson 7 — Non-live environments must fail closed

If live acknowledgements or live credentials leak into paper/demo mode, preflight should reject the environment rather than “do its best.”

---

# R. OLLAMA / LOCAL AI MEMORY

AURA was explicitly developed to use local AI through Ollama for low-cost experimentation.

Relevant historical/runtime lessons:

- local models can create memory/queue pressure;
- model timeout and concurrency controls matter;
- model compatibility can change;
- one-click Windows launcher was added;
- local AI is optional intelligence, not authority;
- structured outputs are preferable to persisting private free-form reasoning;
- hardware limits must be respected.

Typical historical examples used `qwen3` and other local models. Do not assume a specific local model is permanently required; route based on actual availability and validated capability.

---

# S. DATA / BROKER MEMORY

The project has explored or implemented foundations for:

- Coinbase public crypto;
- Bybit public crypto;
- OKX public crypto;
- Binance/Kraken foundations;
- Exness/MetaTrader 5 DEMO;
- Dhan Indian market;
- Shoonya;
- Flattrade;
- OANDA practice/read-only.

Never assume all adapters are equivalent. Each requires connector-specific evidence for:

- authentication;
- sessions;
- heartbeats;
- rate limits;
- reconnect;
- symbol/instrument mapping;
- tick/lot/expiry rules;
- order semantics;
- rejection;
- partial fills;
- reconciliation;
- margin/settlement behavior.

---

# T. SECURITY MEMORY

Never commit:

- API keys;
- broker passwords;
- access tokens;
- TOTP secrets;
- live approval identifiers;
- private certificates;
- secret database URLs.

Use environment variables or a proper secret manager.

Current repository security direction includes `.env` ignore behavior, `.env.example` with blank secrets, CodeQL, Dependabot, non-self-modifying CI, and production preflight.

The tablet/browser is a cockpit, not the trust boundary. Persistent services should run in controlled environments with reliable storage and monitoring.

---

# U. CHATGPT → CLAUDE / OTHER AI HANDOFF CONTRACT

When another AI continues AURA, it must do this before code changes:

```text
1. Read docs/AURA_PROJECT_MEMORY_A_TO_Z.md
2. Read README.md
3. Read docs/IMPLEMENTATION_STATUS.md
4. Read docs/PRODUCTION_READINESS.md
5. Inspect the current branch and `git log`
6. Inspect the exact files involved
7. Run or inspect relevant tests before changing behavior
8. State the current evidence level: REAL / PARTIAL / MOCK / UNVERIFIED
9. Make the smallest safe change
10. Add/update tests
11. Update project memory/change log when the change affects intent, architecture, contracts, safety, or milestone state
12. Do not remove safety gates to make a test/demo work
```

### Required handoff behavior

The next AI must **not**:

- restart AURA design from scratch;
- replace existing modules merely for stylistic preference;
- invent missing evidence;
- call a backtest “live proof”;
- call public-data shadow results “broker evidence”;
- allow an LLM to bypass RiskEngine;
- directly enable live trading;
- commit secrets;
- silently alter constitutional rules;
- overwrite historical lessons without recording the reason.

---

# V. CHANGE LOG PROTOCOL — EVERY SMALL CHANGE MATTERS

From this point onward, meaningful changes should be recorded in this document or a linked machine-readable change log.

Use this format:

```markdown
### YYYY-MM-DD — CHANGE-ID
**Commit:** `<sha>`
**Area:** `<area>`
**What changed:** <precise statement>
**Why:** <problem / reason>
**Evidence:** <tests / command / artifact>
**Status:** REAL | PARTIAL | MOCK | UNVERIFIED
**Risk impact:** <none / low / medium / high>
**Follow-up:** <next action>
```

A change is not “done” simply because the code compiles. The evidence must match the claim.

---

# W. KNOWN GITHUB MILESTONES — VERIFIED COMMIT HISTORY EXCERPT

The repository contains a dense August 2026 engineering history. Major verified semantic milestones include:

- production operations package;
- fail-closed deployment preflight;
- evidence-based production release gate;
- production health snapshot model;
- release-evidence evaluator;
- production environment template;
- hardening of development/release tooling;
- hardened CI release gate;
- removal of self-modifying production workflow;
- CodeQL security scanning;
- dependency monitoring;
- non-root production container target;
- container build exclusions;
- production deployment/runbook;
- fail-closed behavior when live acknowledgements leak into non-live modes;
- production paper/demo hardening;
- bounded autonomous strategy mutation;
- public live strategy lab;
- strategy population refresh/evolution;
- no-key public market connector catalog;
- autonomous strategy lab validation/repair;
- one-shot public live-data smoke validation;
- local Ollama structured reasoning provider;
- configurable multi-model AI specialist council;
- multi-AI council validation and runtime;
- contextual agent reliability learning;
- contextual reliability-weighted CEO votes;
- adaptive contextual AI model router;
- learning from skipped/dissenting opinions;
- governed Ollama strategy architect;
- strategy blueprint compiler;
- position-aware strategy context;
- explicit exit routing through shared RiskEngine;
- causal blueprint compilation into executable strategies;
- public autonomous intelligence and shadow learning.

The exact commit history remains the definitive record of every tiny code change. Future AIs should use `git log`, commit diffs, and file history rather than trying to reproduce every change manually in this document.

---

# X. HISTORICAL SOURCE ARTIFACTS TO KNOW ABOUT

Saved project artifacts that shaped AURA's continuity include:

- `AURA_AI_OS_Final_Blueprint_2026.pdf` — constitution, architecture audit, risk, self-evolution, roadmap, compliance and Phase-2 plan;
- `AURA_AI_OS_Beginner_Master_Setup_Guide_Hindi.pdf` — practical Windows/public-data/Ollama/DEMO workflow and safe operating rules;
- `CLAUDE_CODE_MASTER_PROMPT.md` — earlier coding/architecture guardrails for AI-assisted continuation;
- historical implementation/model files from older V4/V6 experiments — useful only as history, not current source of truth.

The current GitHub repository must take precedence over stale uploaded zips.

---

# Y. CURRENT STATE SNAPSHOT — 2026-09-08

### What is strongly evidenced in repository documentation/code

- substantial financial core;
- independent risk authority;
- deterministic order state machine;
- paper broker;
- WAL / checkpoint / recovery;
- reconciliation;
- multiple market-data adapters;
- deterministic specialists;
- structured multi-AI council;
- adaptive reliability routing;
- bounded strategy factory/evolution;
- causal backtest path;
- public shadow runtimes;
- production preflight / health / release gate;
- security and CI controls.

### What remains externally gated / needs forward evidence

- long-duration operation on the intended host/VPS;
- 1,000+ broker-origin forward trades/decisions over 30+ days under the current default gate;
- validation across multiple real market regimes;
- broker-specific fill/reject/reconnect/reconciliation fault evidence;
- venue-specific margin / freeze / lot / tick / expiry / settlement / liquidation validation;
- zero unresolved critical incidents / reconciliation failures / data-integrity incidents during release window;
- strategy stage transition to `PAPER_VALIDATED` and then human `APPROVED`;
- eligible `ProductionReleaseGate` manifest using `LIVE_BROKER` evidence;
- controlled live canary and subsequent evidence-based scale-up.

### Honest maturity interpretation

AURA is a **substantial paper/demo research and execution platform**, not yet proven as unrestricted autonomous real-money trading infrastructure.

---

# Z. ULTIMATE NORTH STAR — DO NOT LOSE THIS IN FUTURE AI SESSIONS

The purpose of every future commit is to move AURA toward this system:

```text
                    AURA AI OS
                         │
              CONTINUOUS OBSERVATION
                         │
         ┌───────────────┼────────────────┐
         │               │                │
      MARKET           WORLD           KNOWLEDGE
       DATA             MODEL             PLANE
         │               │                │
         └───────────────┼────────────────┘
                         ▼
                    ATTENTION
                         │
                         ▼
              SPECIALIST INTELLIGENCE
        ┌────────────┬────────────┬────────────┐
        │ Technical  │ SMC/ICT    │ Volume     │
        │ HTF        │ Options    │ Macro      │
        │ Regime     │ Forecast   │ Execution  │
        └────────────┴────────────┴────────────┘
                         │
                         ▼
                 BULL / BEAR / CF
                         │
                         ▼
              RELIABILITY-WEIGHTED CEO
                         │
                         ▼
                    ABSTAIN / ACT
                         │
                         ▼
                  INDEPENDENT RISK
                    ║ VETO POWER ║
                         │
                         ▼
                  ORDER STATE MACHINE
                         │
                         ▼
             PAPER / DEMO / BROKER EXEC
                         │
                         ▼
               LEDGER + WAL + AUDIT
                         │
                         ▼
             OUTCOME / MISSED TRADE
                         │
          ┌──────────────┼───────────────┐
          ▼              ▼               ▼
      RELIABILITY      MEMORY         STRATEGY
       LEARNING        LEARNING        EVOLUTION
          │              │               │
          └──────────────┼───────────────┘
                         ▼
               VERIFIED CHALLENGERS
                         │
                         ▼
                 PAPER / CANARY
                         │
                         ▼
              HUMAN-GOVERNED SCALE
```

AURA should become **smarter through evidence, not permission to improvise with money**.

The long-term moat is not a particular LLM. It is the quality of:

- point-in-time data;
- decision ledger;
- negative memory;
- validation history;
- execution observations;
- governance;
- reproducibility;
- failure knowledge.

**Every future AI must preserve this north star.**

---

# FINAL CONTINUITY RULE

When a future AI receives a vague instruction like “continue AURA,” its first question internally should be:

> **What is the current repository truth, what changed since the last known state, what evidence exists, what remains unproven, and which single highest-value next change moves AURA toward the north star without weakening the constitution?**

That is the AURA handoff contract.
