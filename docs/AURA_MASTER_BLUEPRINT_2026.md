# AURA AI OS — Master Blueprint 2026

This document is the binding product/engineering blueprint for AURA. It consolidates the original project intent, accumulated engineering decisions, the multi-agent constitution, and 2026 research into advanced agentic/quant systems.

## 1. Product identity

AURA is not a signal bot, chart indicator, one-strategy EA, one-LLM trader or broker-specific script.

AURA is a **self-improving, broker-agnostic, multi-market AI trading operating system** designed to continuously perceive markets, combine heterogeneous evidence, reason through multiple independent specialist agents/models, protect capital through a deterministic financial-risk authority, execute first in simulation/paper environments, learn from realized outcomes, and promote only validated strategy/model versions through controlled governance.

The engineering target is institutional-quality discipline while remaining practical for retail-accessible broker/exchange APIs.

## 2. User-facing goal

AURA should work as one coordinated trading desk for the user:

- scan supported markets continuously
- scan several timeframes concurrently
- detect valid scalping, intraday, swing and positional opportunities
- explain why a setup exists and what invalidates it
- combine technical, structural, volume, derivatives, macro, news and cross-asset evidence
- use multiple AI/model families rather than trust one model
- paper-trade opportunities autonomously
- measure actual execution costs/slippage
- backtest and stress-test candidates automatically
- learn which models/setups work in which regimes
- generate improved immutable research candidates
- retire/degrade models when live-paper calibration deteriorates
- protect portfolio capital independently of any AI opinion
- preserve a complete audit trail

AURA must not force trades merely to meet a daily quota. Broad scanning should create opportunity frequency; quality/risk gates determine whether a trade is valid.

## 3. Priority markets

### India

- NSE/BSE equities
- NIFTY and BANKNIFTY futures/options
- stock futures/options where liquidity/data supports research
- MCX Gold, Crude Oil, Natural Gas and other supported liquid contracts

### FX / metals

- XAUUSD is a priority research instrument
- major FX pairs where reliable broker/API data is available

### Crypto

- BTC/ETH and broader liquid spot/futures universes
- Binance public/testnet and Kraken are priority connector families

### Global markets

- major indices/equities where reliable point-in-time datasets and compliant account connectivity exist

## 4. Priority timeframes

- 1m
- 5m
- 15m
- 30m
- 1h
- 4h
- Daily

XAUUSD 1m/5m and NIFTY options 1m/5m remain high-priority research modes, but fast execution is enabled only after realistic latency/spread/slippage evidence exists.

## 5. One authority chain

```text
Live/Historical Data Sources
          |
          v
Canonical Live Data Plane + Symbol/Contract Mapping
          |
          v
Point-in-Time Data Quality / Freshness / Sequence Gates
          |
          v
Regime + Market Context Builder
          |
          +-----------------------+
          |                       |
          v                       v
Layered Memory / RAG        Probabilistic Forecast Models
          |                  Chronos/TimesFM/Moirai/ML/etc.
          |                       |
          +-----------+-----------+
                      v
            Concurrent Specialist Team
                      |
          Bull / Bear / Devil / Counterfactual Review
                      |
                      v
                  CEO Synthesis
                      |
                      v
             Agent Evidence Risk Policy
                      |
                      v
          Independent Financial Risk Engine
                      |
          reject / resize / allow / freeze
                      |
                      v
              Order State Machine
                      |
                      v
             Paper / Broker Adapter
                      |
                      v
                    Fills
                      |
                      v
 Portfolio Ledger + WAL + Reconciliation + Audit
                      |
                      v
       Outcome / Model / Strategy Evaluation
                      |
                      v
       Governed Autonomous Research Loop
```

No LLM/model/agent majority may bypass a downstream authority layer.

## 6. Human-like cognitive architecture

“Human-like” means explicit cognitive functions, not a claim that the software is conscious.

### Perceive

Consume live/historical:

- trades/ticks
- OHLCV
- order book/depth
- spread and liquidity
- open interest
- option chain
- Greeks/IV/skew/term structure where available
- funding/liquidations for crypto derivatives
- macro releases/calendar
- news/sentiment
- fundamentals/filings
- cross-asset state
- broker/execution state

### Orient

- symbol/contract normalization
- data-quality/freshness checks
- higher-timeframe context
- trend/range/chop regime
- volatility state
- liquidity/execution state
- portfolio state

### Recall

Layered point-in-time memory:

- working memory
- episodic trade memory
- semantic knowledge
- negative/failure memory
- incident memory
- regime memory

Future outcomes cannot enter historical decisions.

### Forecast

Run several heterogeneous models concurrently when appropriate:

- time-series foundation models
- tabular/gradient boosting models
- sequence models
- calibrated classical statistical models
- validated finance/reasoning models for event interpretation

Normalize outputs into probability/quantile distributions. Ensemble weight comes from AURA-measured calibration/reliability, not model reputation.

### Analyze

Default specialist roles:

1. HTF Bias
2. SMC/ICT Structure
3. Technical
4. Volume/VWAP
5. Probabilistic Forecast
6. Options/Volatility
7. Macro/Sentiment
8. Cross-Market
9. Regime
10. Execution Quality

Provider-backed AI agents may be added to these roles or used as independent challengers.

### Challenge

Before financial action, preserve:

- bull case
- bear case
- neutral/risk evidence
- disagreements
- failed/missing agents
- counterfactual invalidation questions

Unanimous AI agreement is not automatically treated as truth.

### Synthesize

CEO layer creates an auditable decision memo with support/opposition/abstentions and uncertainty. CEO is advisory and has no broker credentials.

### Decide financially

The deterministic RiskEngine is final financial authority.

### Observe and learn

After fills/outcomes:

- record fees/slippage
- reconcile positions/orders
- update model calibration by market/regime/task
- detect model/strategy drift
- create failure/incident memory
- generate new research hypotheses

## 7. Signal evidence universe

AURA should validate and combine, rather than blindly stack, features such as:

- EMA 8/21/50/200
- RSI 14
- MACD 12/26/9
- Supertrend
- Bollinger 20/2
- ATR / Keltner
- VWAP / anchored VWAP
- OBV / VPT
- relative volume
- pivots / support-resistance
- divergence
- market structure / BOS / CHoCH-style causal features
- liquidity sweep/reclaim
- displacement / imbalance-style features
- higher-timeframe bias
- volatility/regime/chop filters
- option OI/volume/IV/Greeks/skew
- order-book imbalance/spread/depth
- macro/news/event state
- cross-market confirmation

Every feature must prove incremental out-of-sample value. More indicators do not automatically mean more accuracy.

## 8. Model strategy

AURA must not run every expensive AI model on every tick.

### Fast path

Continuous/near-continuous deterministic or lightweight models:

- data quality
- structure
- trend/technical
- volume/VWAP
- order book
- execution quality
- regime
- low-latency classifiers

### Forecast path

At configured candle/event boundaries:

- several time-series models in parallel
- calibrated quantile/probability ensemble
- explicit disagreement score

### Deep-reasoning path

Only when event/opportunity value justifies cost/latency:

- strongest validated reasoning model
- finance-language specialist where useful
- macro/news/fundamental research
- bull/bear critique
- CEO synthesis

### Shadow challengers

Non-primary models may run in shadow/paper mode so AURA continually measures whether a challenger should replace a champion.

## 9. Model learning and promotion

AURA tracks model performance by:

- task
- market
- timeframe where applicable
- regime
- calibration/Brier score
- hit rate
- latency
- reliability
- cost

A historically strong model is not trusted forever.

Drift detection compares reference vs recent paper/shadow performance. A challenger may replace a champion only after sufficient samples and material reliability/calibration improvement under policy.

A model can be demoted without changing deployed strategy code.

## 10. Autonomous strategy research

Self-improvement is allowed only in a research sandbox.

```text
Observe Failure / Opportunity
        |
        v
Research Hypothesis
        |
        v
Immutable Candidate Strategy/Factor/Model Version
        |
        v
Backtest
        |
        v
Walk-Forward OOS
        |
        v
Monte Carlo / Robustness / Stress
        |
        v
Autonomous Paper Trading
        |
        v
Measured Evaluation
        |
   +----+----+
   |         |
Reject    PAPER_VALIDATED
   |         |
Negative    Human Approval Required
Memory      for final APPROVED/live eligibility
```

AI may learn from a failed candidate and create the next candidate. It may never overwrite the currently deployed live strategy directly.

## 11. Backtesting standard

Backtests must be causal and reproducible:

- closed-candle signals
- next-bar or realistic event execution
- no repainting
- no future macro/news revisions
- no survivorship/lookahead leakage
- transaction costs
- spread/slippage
- latency assumptions
- partial fills/order types where appropriate
- futures expiry/roll mechanics
- options chain point-in-time replay where data permits
- multi-symbol shared capital/risk
- deterministic event scheduling
- dataset/content/code/config hashes

Historical programs should include 2020–2024 legacy requested windows and expand to more recent/longer data as sources become available.

## 12. Paper trading standard

Paper mode is not a cosmetic signal log.

It should:

- scan live/demo feeds continuously
- place simulated orders itself
- maintain broker-style order state
- apply realistic fees/slippage
- journal fills
- update portfolio
- periodically reconcile
- stop/freeze on critical mismatch
- record every agent/model decision
- compute trade-level net outcomes
- update model performance
- create paper-validation evidence

Paper promotion requires enough trades, positive net expectancy after costs, acceptable profit factor/drawdown, and zero or tightly bounded reconciliation/operational incidents according to policy.

## 13. Financial risk hierarchy

Independent deterministic controls include/target:

- kill switch
- daily loss budget
- drawdown budget
- max order notional
- max gross exposure
- per-symbol concentration
- asset-class/sector concentration
- liquidity/spread/slippage limits
- stale-data/risk-state blocks
- Historical VaR
- Parametric VaR
- CVaR / Expected Shortfall
- annualized volatility
- correlation
- stress scenarios
- portfolio/factor concentration
- futures margin and liquidation headroom
- option Greeks aggregate exposure
- multi-currency cash risk

Protective reduction/flattening remains available when new risk is blocked.

## 14. Live data plane

Canonical event domains include:

- MARKET_TICK
- ORDER_BOOK
- CANDLE
- OPEN_INTEREST
- OPTIONS
- GREEKS
- FUNDING
- LIQUIDATIONS
- MACRO
- ECONOMIC_CALENDAR
- NEWS
- FUNDAMENTAL
- CROSS_ASSET
- EXECUTION

### Initial connectors

DhanHQ v2:

- Indian market tick/quote/OI/FULL depth binary feed
- option chain/Greeks/IV/OI
- later sandbox/account order adapter

Binance:

- Spot public/testnet streams
- trades/book/depth/closed klines
- later futures/funding/liquidation/testnet execution

Kraken:

- existing closed-candle feed foundation
- extend trade/depth where useful

Macro/fundamental:

- FRED/ALFRED vintage-aware macro
- SEC EDGAR/XBRL for US fundamentals
- other trusted sources only with timestamp/provenance contracts

## 15. Broker abstraction

AURA stays broker-agnostic. Broker-specific capabilities are adapters, not strategy dependencies.

Every adapter needs:

- symbol/contract mapping
- capability matrix
- order-id/client-order-id semantics
- rate-limit handling
- reconnect policy
- idempotency policy
- reconciliation
- sandbox/paper tests
- external secrets

No broker credential is stored in repository code or exposed to AI prompts.

## 16. Accuracy objective

There is no honest guaranteed win rate.

AURA's measurable optimization objectives are:

- positive out-of-sample expectancy after all realistic costs
- probability calibration
- drawdown/tail control
- stable performance across regimes
- statistically defensible incremental value vs simple baselines
- acceptable trade frequency from broad scanning
- low execution/reconciliation error rate

Win rate is tracked by setup/market/timeframe/regime but is never the only optimization target.

## 17. Explainability and audit

For each decision, AURA should be able to reconstruct:

- exact point-in-time market/macro/news evidence
- memory visible then
- forecast models and versions
- model routing decision
- specialist outputs/failures
- bull/bear/counterfactual review
- CEO memo
- agent-policy gate
- financial-risk sizing/rejection
- order mapping
- fills/fees/slippage
- portfolio impact
- subsequent outcome
- later research evaluation

If a material decision cannot be reconstructed, the path is not production-ready.

## 18. Deployment stages

1. Engineering unit/integration tests
2. Historical deterministic research
3. Walk-forward/Monte Carlo robustness
4. Live-data shadow mode
5. Autonomous paper/demo trading
6. Extended operational/reconciliation validation
7. Human-approved tiny canary live deployment
8. Controlled scale-up only after evidence

Current AURA status remains **engineering/research + autonomous paper foundation**, not unrestricted live-money automation.

## 19. Permanent non-negotiables

- no AI direct broker execution bypass
- no AI override of independent RiskEngine
- no AI final live strategy approval
- no live self-modifying deployed code
- no future/revision leakage
- no fabricated missing evidence
- no forced trade quota
- no guaranteed accuracy/profit claims
- no secrets in source/prompts
- no separate permissive live logic that bypasses tested financial primitives
- no social-media/repository performance claim treated as proof without AURA's own independent validation
