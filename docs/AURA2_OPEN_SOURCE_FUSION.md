# AURA 2 — Open-Source Fusion

AURA 2 extends the existing AURA AI OS instead of replacing its audited financial core.

## Goal

Reuse proven open-source ideas and permissively licensed components while preserving
AURA's permanent authority chain:

research -> validation -> CEO evidence -> independent RiskEngine -> execution -> reconciliation.

External models, agents, RL policies and research frameworks remain advisory. They cannot set
position size, disable kill switches, move funds, bypass drawdown controls, or directly submit
orders.

## Source projects

| Project | License | AURA 2 use |
|---|---|---|
| Microsoft Qlib | MIT | optional quant research/model workflow |
| Microsoft RD-Agent | MIT | autonomous experiment/research loop |
| TradingAgents | MIT | multi-agent research/debate patterns |
| FinRL-X | Apache-2.0 | RL and portfolio research patterns |
| Freqtrade/FreqAI | GPL-3.0 | architecture reference only in AURA core |
| Nexus Trader MT5 | AGPL-3.0 | architecture reference only in AURA core |

GPL/AGPL projects are not vendored into the AURA core by this branch. Any future use must remain
separately licensed or be independently reimplemented.

## First implemented AURA 2 layer

- source-project/license registry
- hard guard against accidental GPL/AGPL code vendoring
- M1/M5/M15/M30/H1/H4/D1 consensus engine
- execution-timeframe vs higher-timeframe alignment
- regime classification: TREND/RANGE/TRANSITION/HIGH_VOLATILITY
- bounded restart-safe strategy performance memory
- external research evidence gateway
- research candidates can graduate only to AURA validation, never directly to live execution

## Next integration sequence

1. Adapt existing AURA market snapshots into the multi-timeframe consensus input.
2. Add optional Qlib research adapter and artifact import.
3. Add RD-Agent experiment adapter behind a local process boundary.
4. Add TradingAgents-style bull/bear/research-manager adapter using AURA's existing free Ollama council.
5. Add FinRL-X-compatible offline RL experiment runner.
6. Feed all promoted candidates through existing causal backtest, purged walk-forward, Monte Carlo,
   sealed holdout, paper/demo forward evidence, then explicit owner approval.
7. Surface AURA 2 research candidates, MTF consensus and learning stats in the existing Command Center.

No imported framework receives broker credentials or direct order authority.
