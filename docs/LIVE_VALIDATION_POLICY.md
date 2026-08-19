# AURA AI OS — Live Validation & Professional Trading Policy

This policy is binding for AURA's current research/demo stage.

## 1. What “professional trader” means in AURA

AURA must optimize both sides of decision quality:

- **precision:** reduce false entries, wrong-direction trades, bad execution and regime-inappropriate risk;
- **recall:** detect and measure material opportunities the system left FLAT or filtered out;
- **expectancy:** prefer robust positive net expectancy over cosmetic win-rate targets;
- **risk discipline:** no intelligence layer may weaken the independent financial RiskEngine;
- **execution realism:** spreads, slippage, fees, liquidity, lots, contract rules and broker state matter.

Zero losing trades and zero missed opportunities are not achievable guarantees in a stochastic market. AURA therefore measures both failure classes explicitly and improves them under forward evidence rather than claiming perfection.

## 2. Live data is mandatory for paper-champion promotion

Historical, replay or synthetic data may be used for:

- research;
- hypothesis generation;
- fast candidate search;
- causal backtests;
- walk-forward testing;
- Monte Carlo/robustness;
- sealed chronological holdout testing.

They **cannot** by themselves create a paper champion.

A paper brain challenger is promoted only from outcome samples whose provenance is `LIVE_BROKER`, whose decision timestamp is later than the challenger's creation timestamp, and which pass the configured forward paper gates.

Every paper champion artifact must retain:

```text
validation_source = live_broker
forward_only = true
paper_validated = true
live_approved = false
live_money_enabled = false
```

## 3. No future leakage

At decision time AURA may consume only data whose observation/close timestamp is visible at that time. Future bars are allowed only later for outcome labeling, missed-opportunity auditing and research evaluation.

Live decisions use closed candles. Historical warm-up excludes forming bars. Missing market bars are not fabricated to make an indicator look complete.

Walk-forward research must set `purge_size` to at least the longest forward label
or holding horizon used to fit or select a candidate. Purged observations are
excluded from the training slice so their future labels cannot overlap the OOS
window. Because they are already observable by the test boundary, they may warm
causal indicators, but they must never contribute training or fitness evidence.

## 4. Wrong-trade and missed-trade measurement

AURA's live opportunity audit classifies future material moves as:

- `captured`
- `missed_flat`
- `wrong_direction`
- `blocked_safety`
- `no_material_move`

A material move is defined by a configurable future horizon and ATR-normalized threshold. This audit is ex-post only; it never leaks the future move back into the original decision.

The main learning status must expose at least:

- material opportunities;
- captured opportunities;
- capture rate;
- missed-flat opportunities;
- wrong-direction decisions;
- safety-blocked opportunities;
- forward challenger sample count;
- paper P&L / expectancy / profit factor / drawdown where available.

## 5. Two-stage universe scanning

AURA must not solve broad coverage by running expensive AI on every instrument every tick.

### Stage A — broad radar

Use cheap causal market features across the enabled broker universe to avoid fixed watchlists and find changing opportunity clusters.

### Stage B — deep desk

The strongest candidates plus all open-position symbols receive deeper data and the full specialist desk, including where available:

- multi-timeframe candles;
- volume/VWAP;
- OI;
- order-book/depth;
- bid/ask spread;
- options chain / Greeks / IV;
- macro/news/cross-market context;
- forecast/model challengers.

A radar score is never itself a trade signal.

## 6. Broker/data separation

Current supported stage is:

```text
LIVE BROKER MARKET DATA
        -> AURA intelligence
        -> independent RiskEngine
        -> INTERNAL PAPER / GUARDED DEMO
```

Real-money order routing is intentionally disabled in self-evolving runners.

Broker/API credentials must come from environment variables or a secret manager on the runtime machine. They must never be committed to GitHub, stored in strategy genomes, written into agent prompts, or persisted in AURA audit logs.

## 7. Exness / MT5 current path

The self-evolving MT5 runner uses an MT5 DEMO account for live market data and verifies DEMO account state before guarded MT5 trading calls can exist. The default self-evolving runner executes internally on PaperBroker while collecting live broker-origin decision outcomes.

## 8. Dhan / Indian current path

The self-evolving Dhan runner uses:

```text
Dhan live Ticker universe
        -> broad radar
        -> dynamic deep shortlist
        -> Dhan Full volume/OI/depth/spread
        -> causal historical warm-up + live closed candles
        -> 10-agent AURA desk
        -> independent RiskEngine
        -> internal PaperBroker
        -> live outcome + missed-opportunity audit
        -> governed evolution
```

Indexes such as NIFTY/SENSEX are market-data context instruments, not direct trade instruments. Futures/cash contracts keep their broker/exchange metadata and position sizes are constrained by canonical lot/quantity rules.

## 9. Real money remains a separate later stage

A paper champion never becomes live-approved automatically. Real-money eligibility requires sustained forward evidence, broker-specific reconciliation and failure testing, margin/contract validation, monitoring/alerts, canary deployment and explicit human approval.
