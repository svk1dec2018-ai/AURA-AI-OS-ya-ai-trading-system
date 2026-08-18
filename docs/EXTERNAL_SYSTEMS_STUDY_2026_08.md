# AURA AI OS — External AI Trading Systems Study (August 2026)

This document records what AURA should learn from current public AI/quant systems and, equally important, what it must **not** copy blindly.

A public repository, video, paper, social-media demo or claimed return is not evidence that a system is safe or profitable in AURA's target markets. Features are imported only when they strengthen causal research, data quality, memory, portfolio construction, risk, execution, observability or governed learning.

## 1. TradingAgents

**Pattern studied**

- trading-firm style multi-agent organization;
- fundamental, sentiment and technical analysts;
- bull/bear debate before a trader/portfolio decision;
- explicit risk-management role;
- structured decision logs and checkpoint/resume patterns in current implementations.

**AURA mapping**

- retain independent specialist agents rather than one giant prompt;
- keep bull/bear/counterfactual deliberation;
- preserve a CEO synthesis layer;
- persist every specialist evidence item and failure;
- resume from durable state after runtime restarts.

**Do not copy**

- an LLM trader must not directly own broker credentials or financial risk limits;
- text confidence is never sufficient evidence for order sizing.

## 2. Microsoft RD-Agent(Q) + Qlib

**Pattern studied**

- automated quantitative R&D loop;
- factor/model co-optimization;
- propose -> implement -> evaluate -> feedback;
- persistent knowledge from successful and failed experiments;
- Qlib-backed model/factor experimentation.

**AURA mapping**

- use a separate Research Lab that can create hypotheses, factors and challengers;
- record failed experiments as negative memory;
- use walk-forward, sealed holdout and Monte Carlo before forward paper;
- allow research automation to reach candidate/paper stages, never automatic live approval.

**Do not copy**

- research success must not mutate the currently deployed strategy in place;
- offline benchmark improvements are not live-trading proof.

## 3. FinRL-X

**Pattern studied**

- modular deployment-consistent portfolio architecture;
- target-weight/target-exposure contract separating selection, allocation, timing, risk overlay and execution;
- backtest-to-live consistency and explicit transaction costs.

**AURA mapping**

- add a portfolio-intent layer above individual order intents;
- future allocator should support canonical target exposures/weights across brokers;
- convert target exposure into broker-neutral orders only after deterministic portfolio risk checks;
- preserve the same cost/multiplier/margin semantics in research and paper/live paths.

**Do not copy**

- RL policies cannot bypass AURA RiskEngine;
- target weights are intents, not permissions to trade.

## 4. AI-Trader / live autonomous-agent benchmarks

**Pattern studied**

- live comparison of autonomous trading agents;
- real market execution exposes failures not visible in static QA or backtests;
- model intelligence alone does not guarantee trading robustness;
- risk discipline and framework design materially affect results.

**AURA mapping**

- maintain live-data shadow/paper evaluation as a mandatory promotion gate;
- compare challengers on the same market data, execution model and risk constraints;
- score not only return but drawdown, missed opportunities, wrong direction, calibration and execution quality.

**Do not copy**

- short leaderboard windows are not enough for deployment;
- a high-return agent with unstable risk is not a champion.

## 5. FinRobot

**Pattern studied**

- multi-agent financial analysis and tool use;
- deterministic finance calculations separated from LLM narrative/research;
- modular provider/tool architecture.

**AURA mapping**

- calculations, P&L, position accounting, Greeks, margin, sizing and risk remain deterministic code;
- LLMs can explain, research, critique and synthesize but not invent financial state;
- model/provider routing should use measured reliability and latency.

## 6. FinGPT

**Pattern studied**

- finance-focused open/local language models and financial NLP tooling.

**AURA mapping**

- retain FinGPT/open finance models as research or sentiment challengers;
- promote only after task/market/regime-specific evaluation;
- local models can reduce cost and vendor dependence when quality is sufficient.

## 7. FinMem

**Pattern studied**

- layered trading memory;
- recency/salience based retrieval;
- decisions informed by prior market and outcome context.

**AURA mapping**

- working, episodic, semantic, negative, incident and regime memory already exist;
- expand outcome tagging, salience and decay;
- retrieve only point-in-time-visible memory for a decision;
- prevent future outcomes from contaminating the original decision context.

## 8. Fin-Analyst style multi-source analyst systems

**Pattern studied**

- specialists over filings, fundamentals, news, technicals, analyst/social information;
- meta-agent synthesis;
- repeated mistakes when memory is absent;
- fixed thresholds can overtrade sideways/noisy regimes.

**AURA mapping**

- add official filings/news/macro sources with provenance;
- persist error/outcome memory;
- make confidence thresholds regime-aware through governed challenger research;
- require a chop/regime specialist before frequent short-timeframe trading.

## 9. QuantAgents and counterfactual simulation

**Pattern studied**

- analyst/risk/news/manager collaboration;
- simulated trading feedback and predictive-accuracy evaluation.

**AURA mapping**

- keep shadow decisions for trades AURA did not execute;
- measure captured, missed, wrong-direction and safety-blocked outcomes;
- use counterfactual outcomes only after the original decision time.

## 10. Agent Market Arena / self-play environments

**Pattern studied**

- controlled market simulation and self-play for testing agent behavior.

**AURA mapping**

- useful as a research sandbox for stress/adversarial scenarios;
- never substitute synthetic self-play results for forward broker-data validation.

## 11. Time-series foundation models

AURA's model catalog already treats Chronos, TimesFM and Moirai-family models as probabilistic forecast challengers.

**AURA mapping**

- return distributions/quantiles, not a magical BUY/SELL oracle;
- ensemble only after calibration/reliability measurement;
- reject low-trust or highly disagreeing forecasts;
- compare against simple baselines because a complex model must earn its latency/cost.

## 12. Jarvis/Nimbus/social-media autonomous trading demos

Social demos are useful product-interface inspiration, not profitability evidence.

**Useful product pattern**

- voice/text command surface;
- concise market/risk/portfolio briefing;
- visible specialist reasoning and disagreement;
- unified HUD for opportunities, positions, incidents and model health;
- persistent context/memory.

**AURA rule**

A Jarvis-style assistant may request a scan, explanation or paper action. It can never turn voice/text directly into an un-gated live broker order. The authority chain remains:

```text
Human/Assistant command
        -> intent router
        -> AURA intelligence
        -> deterministic RiskEngine
        -> execution policy/reconciliation
        -> broker
```

## 13. YouTube / Instagram / social research policy

AURA may use public videos/posts to discover ideas, products or architectures. Any discovered trading claim must then be verified through one or more of:

- source repository;
- paper;
- official API/provider documentation;
- reproducible code;
- AURA's own causal tests.

If the underlying reel/video cannot be retrieved or independently verified, AURA records it as inspiration only and does not infer hidden features or performance.

## 14. The resulting AURA cognitive loop

```text
PERCEIVE
  live prices + depth + volume + OI + options + macro + news + filings
        |
        v
REMEMBER
  point-in-time working/episodic/negative/regime memory
        |
        v
UNDERSTAND
  technical + SMC + VWAP/volume + options + macro + cross-market + forecast
        |
        v
DELIBERATE
  bull + bear + counterfactual + disagreement
        |
        v
SYNTHESIZE
  CEO thesis/confidence/abstention
        |
        v
CONTROL RISK
  deterministic exposure + margin + drawdown + portfolio + execution gates
        |
        v
ACT
  paper/demo first; broker-neutral order state/reconciliation
        |
        v
LEARN
  fill quality + P&L + calibration + captured/missed/wrong outcomes + incidents
        |
        +-----------------------> Research Lab challenger loop
```

## 15. What “learn every millisecond” means technically

AURA does **micro-learning** continuously and **macro-evolution** only through governance.

### Micro-learning — safe online updates

Every meaningful market/decision/fill/outcome event may update:

- EWMA prediction error;
- calibration error;
- regime statistics;
- spread/slippage/latency;
- captured/missed/wrong-direction rates;
- memory salience;
- drift state.

This path has **zero broker authority** and cannot mutate live-approved strategy parameters.

### Macro-evolution — controlled change

When micro-learning detects enough evidence of drift or failure:

```text
Research trigger
 -> hypothesis/candidate
 -> causal backtest
 -> walk-forward
 -> Monte Carlo / robustness
 -> sealed holdout
 -> NEW forward live-data shadow/paper evidence
 -> paper champion
 -> human/live governance
```

This separation is a non-negotiable defense against online overfitting and unstable self-modifying live strategies.

## 16. AURA advantage to build toward

AURA should not try to beat every public project by adding more agents. Its defensible advantage is the integration of:

1. universal broker/data discovery;
2. point-in-time evidence and memory;
3. multi-agent disagreement, not forced consensus;
4. deterministic financial authority;
5. realistic execution and reconciliation;
6. explicit false-positive **and** false-negative learning;
7. champion/challenger model routing;
8. continuous online measurement without unsafe live mutation;
9. research automation with forward-live promotion gates;
10. one observable, explainable operating system across markets.
