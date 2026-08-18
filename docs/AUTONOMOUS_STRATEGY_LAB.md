# AURA Autonomous Strategy Intelligence Lab

This layer gives AURA broad research freedom while keeping execution safety deterministic.

## Objective

AURA may continuously:

1. observe live/public market events;
2. build causal second/minute candles;
3. evaluate a population of strategy hypotheses;
4. create forward-only virtual trade plans;
5. resolve those plans only after future market data arrives;
6. rank strategies by sample-aware win rate, expectancy and profit factor;
7. retain stronger live-shadow elites;
8. mutate bounded alpha genes and inject new challengers;
9. hand the strongest candidates to formal causal backtest / walk-forward / Monte Carlo / paper validation.

It may **not** mutate RiskEngine controls, broker permissions, kill switches, max-loss policy or live approval.

## No-key live learning

The easiest current live-data research path needs no broker account and no API key:

```powershell
python examples/run_free_public_strategy_lab.py
```

Default source and symbols:

```text
Coinbase public market trades
BTC-USD
ETH-USD
```

Alternative Bybit public feed:

```powershell
python examples/run_free_public_strategy_lab.py `
  --provider bybit `
  --symbols BTCUSDT ETHUSDT
```

The runtime builds these research timeframes by default:

```text
1s, 5s, 15s, 30s, 1m, 3m, 5m
```

No orders are submitted. Results are shadow research evidence only.

## What is recorded

State directory:

```text
runtime/free_public_strategy_lab/
```

Important files:

```text
status.json
top_research_seeds.json
```

`status.json` includes:

- live ticks seen;
- closed research candles;
- generated strategy plans;
- resolved forward plans;
- population generation/refresh count;
- total strategies created;
- pending plans;
- discarded pending plans during population refresh;
- top strategies with resolved sample count, wins/losses/flats, win rate, expectancy bps, profit factor and score.

`top_research_seeds.json` contains the strongest current research genomes for formal validation. It always remains `research_only=true` and `live_approved=false`.

## Strategy freedom

The current safe strategy grammar can compose/evolve:

- trend / hybrid / breakout / mean-reversion style;
- EMA periods;
- RSI period and thresholds;
- momentum lookback;
- breakout lookback;
- Bollinger deviation behavior;
- volume participation filter;
- ATR/volatility filter;
- feature enable/disable choices;
- minimum evidence-vote requirement.

The wider AURA agent desk separately contributes HTF, SMC/ICT, VWAP/volume, forecast, options/volatility, macro/news, cross-market, regime and execution-quality evidence.

## 80% target

`0.80` is an aspirational research target, not a promised future win rate. AURA deliberately prevents tiny-sample win-rate gaming. A candidate still needs enough trades and must show positive expectancy, profit factor, controlled drawdown and stability.

A 95% candidate on 10 trades is not automatically preferred over an 80% candidate on hundreds/thousands of forward observations.

## Why virtual experience can be huge

One live second-level candle can be evaluated by many strategy candidates at once. For example, a 64-strategy population across multiple symbols/timeframes can create large amounts of hypothetical forward experience without risking money. Increasing research population size is therefore different from firing thousands of real broker orders.

## Formal confirmation

The live shadow lab is an idea-generation and forward-screening engine. Confirmation remains:

```text
LIVE SHADOW RESEARCH
 -> CAUSAL BACKTEST
 -> WALK-FORWARD
 -> MONTE CARLO / ROBUSTNESS
 -> SEALED HOLDOUT
 -> NEW FORWARD LIVE-DATA PAPER
 -> PAPER CHAMPION
 -> BROKER-SPECIFIC CANARY / RECONCILIATION
 -> EXPLICIT HUMAN LIVE APPROVAL
```

This separation lets AURA explore aggressively while keeping real-money deployment conservative.
