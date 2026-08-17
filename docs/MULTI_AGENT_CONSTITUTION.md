# AURA AI OS Multi-Agent Constitution

This document is a non-negotiable architecture contract for AURA's intelligence layer. Future implementations may improve models, providers, prompts, features and orchestration, but they must not weaken these authority boundaries.

## 1. AURA is an operating system, not one trading bot

AURA continuously evaluates multiple markets and timeframes through a coordinated team of specialist intelligence modules. No single model, prompt, indicator or strategy owns the system.

Target market families include:

- Indian equities, indices, futures and options
- commodities including gold/energy where supported
- FX with XAUUSD as a high-priority research instrument
- crypto including BTC/ETH and broader liquid universes
- global equities/indices where reliable data and compliant connectivity exist

Target decision horizons include scalping, intraday, swing and positional modes. Fast timeframes such as 1m/5m are allowed only when data quality, execution simulation and latency assumptions support them realistically.

## 2. Specialist agents work concurrently

The default AURA intelligence round runs independent specialists concurrently so the user receives a combined view rather than a serial chain where one model anchors the others.

Core specialist roles:

1. **HTF Bias Agent** — higher-timeframe trend, structure and directional context.
2. **SMC/ICT Agent** — market structure, liquidity, displacement, imbalance/FVG-style features, sweeps and structural invalidation.
3. **Technical Agent** — EMA, RSI, MACD, Supertrend, Bollinger/Keltner, ATR, pivots, divergence and other validated technical features.
4. **Volume/VWAP Agent** — VWAP, relative volume, OBV/VPT, volume profile and participation evidence.
5. **Options/Volatility Agent** — IV, Greeks, skew, term structure, OI/volume and derivatives context where reliable data exists.
6. **Macro/Sentiment Agent** — economic events, macro context, source-backed news/sentiment and event risk.
7. **Cross-Market Agent** — intermarket confirmation, correlation shifts and related-asset evidence.
8. **Regime Agent** — trend/range/chop/volatility regime, OOD/drift and strategy suitability.
9. **Execution-Quality Agent** — spread, liquidity, slippage, latency and market-impact advisory evidence.

Additional specialists may be added, but independent risk authority must never be converted into a normal voting agent.

## 3. Multiple AI providers/models may participate in the same round

A specialist is provider-agnostic. AURA may run different AI models/providers at the same time, including multiple models covering the same role for diversity or cross-checking.

Provider/model output must be normalized into typed `AgentEvidence`. Provider identity and model identity must be preserved for auditability.

No provider receives broker credentials, direct portfolio mutation rights or deployment authority.

## 4. Evidence before opinion

Every specialist output must carry:

- agent identity and role
- directional intent or explicit abstention
- calibrated confidence
- thesis/reasoning summary
- risk flags
- source references
- source trust/freshness metadata
- point-in-time safety
- model/provider/version metadata where applicable

Future information, post-event leakage and fabricated evidence are forbidden. Missing evidence must remain missing rather than being invented.

External research must pass through the AURA knowledge/RAG firewall with source provenance, publication/observation time, trust weighting, duplicate/version controls and contradiction handling.

## 5. CEO layer synthesizes; it does not execute

The CEO layer receives the full evidence round and produces an auditable decision memo. It must preserve disagreement, abstentions, failures and uncertainty.

The CEO may:

- synthesize specialist evidence
- identify supporting/opposing agents
- produce a directional candidate or abstain
- explain confidence and contradictions
- recommend that a candidate be researched further

The CEO may not:

- submit or cancel broker orders
- bypass the independent risk engine
- directly size a live position
- alter portfolio accounting
- approve a strategy for live deployment
- modify approved/deployed strategy code

A future LLM-backed CEO must obey the same boundaries as the deterministic CEO aggregator.

## 6. Independent Risk Engine is final financial authority

Every directional output — indicator strategy, rules strategy, ML model or multi-agent CEO memo — enters the same governed `DecisionPipeline` and the same independent risk gate.

Risk may reject, resize, transform, hedge, pause, freeze or kill new risk according to policy. Protective exits/flattening must remain possible when new exposure is blocked.

No AI vote can override:

- kill switch
- drawdown/loss budget
- exposure/concentration limits
- stale/bad data gates
- reconciliation freeze
- liquidity/execution constraints
- deployment governance

## 7. One execution path for backtest, paper and live

AURA must not maintain a permissive AI/live path separate from the tested path. Signals from all intelligence sources enter the same domain models and governed order path.

Backtest, paper and live adapters may differ only where venue mechanics genuinely differ; financial invariants, risk authority and event accounting remain shared.

## 8. Durable state and reconciliation precede live trading

Orders, fills and financial state transitions must be journaled durably. On restart, AURA rebuilds state deterministically and reconciles against broker truth.

Unknown/mismatched broker state freezes new risk. AURA must not silently "heal" a position/order mismatch when doing so could hide a duplicate fill, lost order or broker-side exposure.

## 9. Research and self-improvement are governed

AURA may continuously learn from:

- trades and execution outcomes
- errors/incidents
- market regimes
- approved books/papers/research
- exchange and broker documentation
- validated strategy experiments

But self-evolution follows this pipeline:

`Research -> Hypothesis -> Candidate Strategy Version -> Backtest -> Walk-forward -> Monte Carlo/Robustness -> Paper Trading -> Evaluation -> Human Approval or Rejection -> Controlled Deployment`

An AI agent may generate or critique candidates, but it cannot replace a deployed strategy directly or perform final live approval.

## 10. Frequency and accuracy are outcomes, not hard-coded promises

AURA should scan broadly and avoid an artificial bias toward never trading, but it must not force trades to satisfy a daily quota. Trade frequency must come from validated market opportunity, realistic execution and portfolio risk.

Win-rate or accuracy targets are research goals only. They are never guaranteed and must be measured out-of-sample with realistic costs and failure modes.

## 11. Explainability and auditability are mandatory

For every material decision AURA should be able to reconstruct:

- market data/evidence visible at that time
- specialist outputs and failures
- CEO synthesis
- strategy/model/version identities
- risk decision and sizing changes
- submitted order and broker mapping
- fills/fees/slippage
- portfolio impact
- later evaluation outcome

If a decision cannot be reproduced and explained from persisted point-in-time evidence, it is not production-ready.

## 12. User-facing goal

The complete system should work as one coordinated AI trading operating system for the user: continuously scan supported markets/timeframes, surface and evaluate opportunities, combine specialist evidence, protect capital through independent portfolio risk, learn through governed research, and progress from realistic backtesting to paper trading before any controlled live deployment.
