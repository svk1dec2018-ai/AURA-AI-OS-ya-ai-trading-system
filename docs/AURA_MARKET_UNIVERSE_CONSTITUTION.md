# AURA AI OS — Market Universe Constitution

This document is a binding extension of `AURA_MASTER_BLUEPRINT_2026.md`.

AURA is a universal multi-market trading operating system. It must not be implemented as a crypto-only, India-only, forex-only, MT5-only, Dhan-only, or single-symbol system.

## 1. Universal scanning mandate

AURA must continuously discover the tradable instrument universe exposed by every enabled connector and scan eligible instruments across configured timeframes.

The scanner must not rely on a short hard-coded watchlist as the permanent architecture. Connectors should discover available symbols/contracts, normalize them into AURA's canonical instrument model, apply liquidity/data-quality/session/risk eligibility rules, and then scan the resulting active universe.

The goal is broad opportunity discovery across markets while preserving strict evidence and financial-risk gates. AURA must not force a trade when no validated opportunity exists.

## 2. Exness + MetaTrader 5 scope

Exness/MT5 is a first-class AURA venue for the full instrument set actually exposed by the connected Exness MT5 account.

Required supported categories include, where available in the account/region:

- Forex majors
- Forex minors
- Forex exotics
- Gold pairs, especially XAUUSD
- Silver and other available metals
- Energies such as crude oil, Brent and natural gas
- Global index CFDs
- Global stock CFDs
- Cryptocurrency CFDs

AURA should dynamically enumerate MT5 symbols rather than assume a fixed static list. Symbol availability, suffixes, trading sessions, contract size, volume step, tick size/value, margin mode, stops level and execution rules must come from the connected MT5 terminal/account metadata.

AURA's MT5 connector must support:

- symbol discovery
- live ticks
- OHLC history
- multi-timeframe candle construction
- spread monitoring
- market depth when exposed by MT5/broker
- account/equity/margin state
- open positions/orders
- order submission/cancel/modify
- fill/deal history
- reconciliation
- demo execution
- later governed live execution

MT5/Exness must use the same AURA intelligence, risk, order-state, audit and learning path as every other venue. No MT5-specific shortcut may bypass the independent RiskEngine.

## 3. Indian market scope

AURA must cover the Indian exchange-traded universe through DhanHQ and/or another validated Indian broker adapter while remaining broker-agnostic.

Required market scope:

### NSE/BSE cash equities

- eligible listed stocks
- liquid large/mid/small-cap stocks subject to data and liquidity policy
- ETFs where supported

### Index derivatives

- NIFTY futures
- NIFTY options
- BANKNIFTY futures/options where listed and supported
- other exchange-listed index futures/options where available and sufficiently liquid

### Stock derivatives

- eligible single-stock futures
- eligible single-stock options
- all current expiries/strikes that pass liquidity, spread, OI and data-quality rules

### MCX

- Gold
- Silver
- Crude Oil
- Natural Gas
- other supported liquid commodity futures/options where available through the connected broker/data source

The Indian universe must be contract-aware. It must model:

- exchange
- segment
- underlying
- expiry
- strike
- option type
- lot size
- tick size
- freeze quantity
- trading session
- margin requirements
- settlement/expiry rules
- corporate actions where relevant
- instrument lifecycle and symbol roll

## 4. Options intelligence mandate

For Indian index and stock options AURA must not treat each option like an ordinary stock.

The option intelligence path should consume and/or derive:

- underlying price and structure
- strike/expiry map
- call/put side
- OI and change in OI
- volume and relative volume
- implied volatility
- IV percentile/rank where enough history exists
- Delta
- Gamma
- Theta
- Vega
- bid/ask and spread
- market depth/liquidity
- PCR and other aggregate chain features
- skew
- term structure
- expected move
- max-pain-style features only if independently validated
- unusual activity only when statistically defined
- expiry/assignment/settlement risk
- portfolio aggregate Greeks

AURA should decide first whether the opportunity is directional, volatility, relative-value or no-trade, and only then choose an eligible contract/structure.

## 5. A-to-Z opportunity scanner

The scanner should search the entire eligible connected universe, not only a manually selected handful of symbols.

Examples of opportunity families to research/validate include:

- trend continuation
- breakout
- failed breakout
- reversal
- liquidity sweep/reclaim
- BOS/CHoCH-style structural change
- order-block/FVG-style causal structure
- VWAP rejection/reclaim
- volume expansion
- relative strength/weakness
- momentum acceleration/deceleration
- volatility expansion/contraction
- option OI/IV/Greeks dislocations
- cross-market confirmation/divergence
- event-driven macro/news reactions
- regime transitions
- mean reversion where validated

Every opportunity family must remain causal, point-in-time safe and independently validated before it can influence live trading.

## 6. Timeframes

The universal scanner should support at minimum:

- 1m
- 5m
- 15m
- 30m
- 1h
- 4h
- Daily

The architecture may add tick/seconds or other broker-supported periods later, but fast timeframes must not bypass realistic latency/spread/slippage validation.

## 7. Execution modes

Every venue/instrument must support the same governed progression where technically possible:

`BACKTEST -> SHADOW -> PAPER/DEMO -> VALIDATED -> HUMAN-APPROVED LIVE`

AURA should autonomously place and manage paper/demo trades after the relevant research gates pass.

Live trading is an intended AURA capability, but it is not activated merely because a connector exists. Live execution requires valid credentials, venue-specific reconciliation, operational supervision, portfolio-risk limits and a human-approved deployment version.

## 8. Multi-broker capital and portfolio coordination

AURA must operate as one portfolio intelligence layer even when execution is split across brokers/venues.

Examples:

- Exness MT5 for forex/metals/global CFDs
- Dhan for NSE/BSE/F&O/MCX
- Binance/Kraken for crypto where enabled

The Portfolio/Risk layer must see total exposure across connectors so simultaneous agents cannot independently consume the same risk budget.

Risk aggregation must include where relevant:

- gross/net exposure
- asset-class exposure
- currency exposure
- correlated exposure
- futures notional/margin
- option Delta/Gamma/Vega/Theta
- CFD leverage/margin
- broker/account free margin
- concentration
- VaR/CVaR
- stress tests
- daily loss/drawdown limits

## 9. Permanent interpretation of "all markets"

"All markets" means **all instruments legitimately available through enabled, validated connectors and supported by AURA's canonical data/risk/execution model**.

It does not mean inventing access to an exchange or product that a broker does not offer. AURA routes each market to the appropriate connector while preserving one intelligence and risk architecture.

## 10. Permanent priority

AURA's scanner should continuously search broadly enough that opportunity frequency comes from universe breadth and multiple strategies/timeframes, not from weakening entry quality or forcing trades.

Capital protection remains above opportunity frequency.
