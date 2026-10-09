# AURA causal strategy desk — 2026-10-09

This release expands executable research strategies and enriches the existing
technical specialist with an auditable strategy-family assessment. It is a DEMO
candidate, not a completed all-market live trading system or a profitability claim.

## Included setups

| Setup | Family | Conditions |
| --- | --- | --- |
| EMA momentum | Trend | RSI direction and chop rejection |
| MACD momentum | Momentum | Directional regime and chop rejection |
| Supertrend continuation | Trend | Wilder ATR bands and chop rejection |
| Donchian breakout | Breakout | Close beyond prior channel, relative volume, chop rejection |
| Keltner breakout | Breakout | Relative volume and chop rejection |
| Bollinger reversion | Reversion | Range filter |
| RSI range reversion | Reversion | RSI extreme and range filter |
| Liquidity sweep | Structure | Reclaim and premium/discount |
| Order-block retest | Structure | First unconsumed retest after confirmed break |
| Fair-value gap | Structure | Three closed candles, directional regime |
| Structure breakout | Structure | Relative volume and chop rejection |
| VWAP participation | Participation | Session VWAP, relative volume, chop rejection |
| Prior-bar pivot reclaim | Structure | Prior bar pivot levels; premium/discount |
| Confirmed RSI divergence | Reversion | Two-bar delayed pivot confirmation, range gate |

Order-block and liquidity features are explicit OHLC proxies; they do not observe
institutional orders. Donchian and structure ranges exclude the current candle.
Supertrend has a deterministic seed, Wilder ATR smoothing and sequential bands.
Choppiness uses 14 past true ranges. Missing warmup yields no setup.

## Brain behavior

The technical specialist now runs the shared compiled research setups. Its
`features.strategy_desk` stores active setups, market regime, supporting/conflicting
families, vote agreement and the abstention reason. Similar setups in one family
provide one family vote. Internal family disagreement removes that family's
directional support. At least two agreeing families and 60% family agreement are
required for the desk to express direction. This heuristic agreement is **not** a
calibrated probability or proof that families are statistically independent.

The desk enriches the existing technical vote, rather than adding twelve correlated
votes to the CEO. Strong desk disagreement with EMA/RSI makes that specialist
abstain. Desk agreement alone does not create a trade. Existing HTF, SMC, volume,
options, macro/news, forecast, cross-market, execution-quality, reliability and
bull/bear deliberation continue through the existing scanner and risk pipeline.
The desk's research setups are not automatically promoted or deployed as live
strategies. Their advisory features can influence the existing DEMO council.

The CEO's confidence is now capped by supporting evidence strength: unanimous
10%-confidence evidence stays at 10%, rather than becoming 100% from agreement.
A tied long/short vote abstains even with a zero margin threshold. Prime's separate
model ensemble rejects duplicate identities, excludes zero-weight models from
quorum, and honors a dominating abstention score. That model ensemble still needs
its business pipeline wiring; this change does not claim it drives every scan.

## Strategy Studio

Open Research → full workstation → Strategy Studio. Choose the broker symbol,
timeframe and number of closed bars. Fourteen template cards compile an immutable
research candidate; all selected confirmations are required for owner candidates.
Selected range/chop/regime gates are mandatory even when another confirmation
agrees. Backtests use the same compiler and independent RiskEngine. MT5 backtests
require a local DEMO terminal; the UI does not fetch broker history without it.

The compiler rejects unclosed, mixed-symbol, mixed-timeframe, duplicate,
overlapping or reversed consumed candle history. Exit requests remain available
before entry filters, so a range gate cannot prevent an open position's exit.

## GitHub comparison and provenance

Inspected all three public repositories under `svk1dec2018-ai`:

- `aura-prime`: README-only remote main at inspection; this candidate is built in
  the local release branch, retaining its bootstrap history.
- `AURA-AI-OS-ya-ai-trading-system`: source of the existing Prime runtime.
- `aura-new-by-arena`: main tree `f8482ef790ba004a2365c388114b7bae9b3fefed`
  contains only a 20-byte README. Its separate `arena/01a01bd3-aura-new-by-arena`
  branch at `04a92492e5341a4cecb882717c8e254d402313ab` contains a FastAPI/React
  application. Inspected technical/SMC/fusion/CEO/chat modules and feasibility
  document. Adapted its prior-bar pivot and RSI-divergence ideas into native
  Decimal/closed-candle primitives. No whole-file transplantation. The arena CEO
  passes fixed 1,000,000 equity/cash/peak values to risk evaluation, so that path
  was not imported. The existing Prime account-ledger authority remains in place.

External references inspected:

| Project | Inspected license | Use in this release |
| --- | --- | --- |
| [Freqtrade strategies](https://github.com/freqtrade/freqtrade-strategies) | GPL-3.0 | Compared strategy families and its Supertrend adapter; no copied code or runtime dependency |
| [Freqtrade lookahead analysis](https://github.com/freqtrade/freqtrade/blob/develop/docs/lookahead-analysis.md) | GPL repository | Validation reference; no copied code |
| [smart-money-concepts](https://github.com/joshyattridge/smart-money-concepts) | MIT | Compared SMC definitions and availability timing; no copied code or dependency |
| [Backtesting.py](https://github.com/kernc/backtesting.py) | AGPL-3.0 | Compared backtesting approach; retained AURA's existing engine |

SMC `smc.py` blob `110759cc8e063773f4905d437f15932534e7f3b4` labels FVGs
using a next-candle negative shift and swings with forward windows. Such historical
labels require confirmation delays before live use. AURA's new implementation
only emits latest-candle evidence from already closed candles; it does not import
those historical labels. Freqtrade Supertrend adapter blob
`757b15214c0088b38973b3eb0d6bd56bfcfbf56c` was inspected; it delegates to its own
technical library and was not transplanted. No third-party source was vendored. Owner-repository conceptual adaptations are identified above.

## Still required for the original complete aim

Broker credentials/account sessions and venue conformance; broker-origin DEMO
execution evidence; actual out-of-sample/walk-forward and forward validation per
strategy; trained and calibrated ML artifacts; wiring passive distributed roles;
authenticated cross-venue execution certification. Persistent outcome learning,
knowledge retrieval and controlled repair already exist, but adding templates does
not prove profitable autonomous learning. Financial limits and live-money gates
stay independent. No model gets withdrawal, fund-transfer or risk-bypass authority.
