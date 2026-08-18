# AURA AI OS — Truthful Implementation Status — 2026-08-18

AURA is an advanced working codebase, but **not a proven live-money autonomous trading system yet**. This document deliberately separates implemented code from credential-validated connectivity, forward paper evidence and live eligibility.

## Implemented core

- canonical multi-market instrument/universe model;
- dynamic Exness/MT5 universe discovery contract and Windows MetaTrader 5 demo gateway;
- Dhan detailed instrument-master normalization and broad/deep Indian-market planning;
- Binance and Kraken market-data foundations;
- concurrent specialist-agent orchestration and CEO synthesis;
- bull/bear/counterfactual deliberation;
- independent deterministic RiskEngine;
- portfolio ledger, cash/P&L, contract multipliers, quantity rules and risk reservations;
- broker-neutral order state, durable financial journaling and reconciliation foundations;
- internal PaperBroker;
- causal backtest/research foundations;
- research lifecycle, genome/challenger/paper-champion governance;
- point-in-time memory/model/forecast/drift infrastructure;
- missed-opportunity and wrong-direction audit;
- safe event-by-event online measurements with research triggers;
- atomic restart recovery for unresolved opportunity horizons plus deterministic
  rehydration of online-learning measurements from the append-only audit;
- broker-neutral target-exposure planner;
- cross-provider quote consensus/outlier guard;
- free/official external intelligence ingest and live cache;
- live macro/news specialist fallback using explicit structured sentiment only;
- Dhan option-chain/IV/PCR/Greeks/liquidity context in live decisions;
- live-data self-evolving internal-paper runners for MT5 and Dhan;
- bounded autonomous strategy-invention DSL for trend, breakout, mean-reversion and hybrid hypotheses;
- autonomous strategy research farm with concurrent population evaluation/evolution;
- second-level research candles: 1s/5s/15s/30s plus 1m/3m/5m and higher frames;
- no-key public live crypto feeds for Coinbase and Bybit trades/tickers plus OKX ticker redundancy;
- forward-only live shadow strategy lab that can evaluate many candidate plans on every eligible closed research bar without sending orders;
- continuous live population refresh: retain live-shadow elites, mutate bounded alpha genes and inject fresh challengers while preserving market history;
- sample-aware pro-trader research objective with an aspirational 80% win-rate target plus expectancy, profit factor, drawdown and minimum-trade requirements.

## Autonomous strategy intelligence

AURA's strategy-invention layer is deliberately more free than a fixed indicator bot but less dangerous than arbitrary self-modifying Python. It can combine and evolve bounded alpha concepts such as:

- EMA/trend structure;
- RSI state;
- momentum;
- breakout logic;
- Bollinger/mean-reversion behavior;
- relative-volume confirmation;
- ATR/volatility behavior;
- style, lookback, threshold and feature-selection combinations.

The broader specialist desk remains responsible for SMC/ICT structure, VWAP/volume, HTF context, options/volatility, macro/news, cross-market, regime and execution-quality evidence. Strategy invention has **no risk-sizing, kill-switch, broker-permission or live-approval genes**.

The no-key live shadow runtime can create a large amount of forward-only virtual experience from real public market events. These are research plans, not broker orders. High win rate alone cannot confirm a strategy: small-sample or negative-expectancy candidates are penalized.

## Concrete connector code

### Exness / MetaTrader 5

State: `ADAPTER_IMPLEMENTED` for the MT5 DEMO/live-terminal integration path used by AURA. The self-evolving runner uses broker live data but internal paper execution by default. Actual account connectivity requires the user's Windows MT5 terminal and DEMO credentials.

### DhanHQ

State: substantial `ADAPTER_IMPLEMENTED` market-data/options path. Includes instrument master, live Ticker/Full feed, depth/OI/volume, history and option-chain context. Actual connectivity requires the user's Dhan credentials and current Data API access.

### Shoonya / Finvasia

State: `ADAPTER_IMPLEMENTED` for read-only market data. AURA implements runtime session credentials, REST quote/history, current WebSocket touchline protocol, reconnect/resubscription and PIT-safe normalization. Broker order routing is intentionally not enabled.

### Flattrade Pi v2

State: `ADAPTER_IMPLEMENTED` for read-only market data. AURA implements current Pi v2 REST TPSeries and WebSocket touchline/auth protocol. Broker order routing is intentionally not enabled pending broker-specific reconciliation and current regulatory/static-IP deployment checks.

### OANDA v20

State: `ADAPTER_IMPLEMENTED` for read-only practice/live pricing and candle data. The recommended validation environment is `practice`. Order routing is intentionally not enabled.

### Binance

State: market-data/transport foundations implemented, including production/test environment helpers. Full AURA broker execution qualification remains a separate stage.

### Kraken

State: public market-data adapter foundation implemented. Full AURA broker execution qualification remains a separate stage.

### Coinbase public market data

State: `ADAPTER_IMPLEMENTED`, no API key required for AURA's current public ticker/market-trade ingestion. Data only; no broker execution authority.

### Bybit public market data

State: `ADAPTER_IMPLEMENTED`, no API key required for AURA's current public ticker/public-trade ingestion. Data only; no broker execution authority.

### OKX public market data

State: `ADAPTER_IMPLEMENTED` for the current public ticker redundancy path. Data only; no broker execution authority.

## Researched connector catalog — not yet concrete AURA transports

The capability catalog also tracks current official APIs for:

- Upstox;
- Angel One SmartAPI;
- FYERS;
- Zerodha Kite;
- 5paisa;
- Kotak Neo;
- Alice Blue ANT;
- ICICI Breeze;
- cTrader Open API;
- Alpaca;
- Interactive Brokers.

These entries are intentionally marked `RESEARCHED` until actual AURA transport code and tests exist. Listing a broker is not a claim that AURA can already connect or trade through it.

## Live intelligence currently implemented

- RBI official Press Releases RSS;
- RBI official Notifications RSS;
- SEBI RSS;
- GDELT global news discovery/context;
- optional Alpha Vantage News & Sentiment;
- optional FRED macro observations;
- optional SEC EDGAR filings/submissions;
- point-in-time event cache;
- source/trust provenance;
- future-data rejection;
- no headline-to-direction guessing when explicit sentiment is absent.

Dhan and MT5 self-evolving paper paths merge the live intelligence cache into the frozen decision-time metadata used by the specialist desk.

## Continuous learning meaning

AURA does not rewrite a deployed live strategy on every millisecond/tick. It can update research/online state for every meaningful event and second-level bar:

- prediction/calibration error;
- captured/missed/wrong-direction outcomes;
- live-shadow strategy outcomes;
- strategy population rankings;
- spread/slippage/latency;
- regime/drift measurements;
- memory salience.

The public live strategy lab may continuously create new research challengers from proven live-shadow elites. That still does not grant live execution. A strategy intended for money deployment must pass the governed validation path.

## Strategy confirmation path

```text
public/live shadow learning
 -> bounded strategy hypothesis
 -> causal backtest
 -> walk-forward testing
 -> Monte Carlo / robustness
 -> sealed holdout
 -> NEW forward live-data shadow/paper evidence
 -> paper champion
 -> broker-specific canary / reconciliation validation
 -> explicit human live approval
```

Historical/replay or live-shadow experience can accelerate learning, but neither can independently mark a strategy `LIVE_ELIGIBLE`.

## What is still required before live money

1. real credential/session validation for the user's chosen brokers/data providers;
2. sustained multi-regime forward live-data paper/demo evidence;
3. real broker order/fill reconciliation for each execution connector;
4. broker-specific margin, freeze quantity, order-type and rejection-path validation;
5. redundant feed deployment/cross-feed symbol mapping in production;
6. operational alerts and 24x7 monitoring on the chosen host;
7. canary limits and incident drills;
8. current regulatory/static-IP compliance where applicable;
9. explicit live-strategy and live-broker approval.

## Accuracy statement

No honest trading system can guarantee zero losing trades, zero missed opportunities or an 80%+ future win rate. AURA uses 80% as an **aspirational research target**, while confirmation also requires sufficient sample size, positive net expectancy, profit factor, controlled drawdown, robustness and forward evidence. The implementation objective is to measure and reduce both wrong trades and missed opportunities while protecting portfolio capital.
