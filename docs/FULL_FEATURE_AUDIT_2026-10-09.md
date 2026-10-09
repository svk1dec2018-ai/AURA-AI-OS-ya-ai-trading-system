# AURA full feature audit — 2026-10-09

**Verdict: local paper/demo/research software candidate; unrestricted live production NOT READY.** Adding an AI API key alone does not activate every feature.

## Executed checks

| Scope | Evidence | Result |
|---|---|---|
| Python software suite | Full pytest run, 775 tests, zero skipped | PASS |
| Production dashboard | Next build and TypeScript compilation | PASS |
| Real browser / local backend | 11 Playwright tests, no HTTP route mocking | PASS |
| Workstation navigation | All 19 views on 1440px and 390px Chromium | PASS |
| Cockpit navigation | All 5 tabs | PASS |
| Chart controls | Symbol, 7 timeframes and retry; offline error response | PASS guard, broker chart BLOCKED |
| Strategy buttons | All 14 cards compile real research candidates at EURUSD 30m; candidate stays unapproved | PASS |
| Strategy UI backtest | Each of 14 buttons calls actual backend; missing MT5 returns JSON 400 | Correctly BLOCKED, not a completed market backtest |
| Runtime controls | Start, stop, emergency lock, reset; BUY/SELL NO SEND order previews | PASS guards, actual execution BLOCKED |
| Owner assistant | All 6 examples, close, keyboard open/escape, speech toggle and unavailable-voice fallback | PASS |
| Capability explorer | Search and all 7 state filters match catalog | PASS |
| Owner token | Save/clear session storage | PASS |
| API inventory | 18 GET routes, missing API 404, malformed JSON 400 | PASS |
| Synthetic backtests | 14 setups × 7 timeframes × 3 scenarios = 294; fees/slippage, default risk limits | No runtime errors; 182 runs generated fills |
| Actual public history | Coinbase BTC-USD 1h, 299 closed bars, 2026-09-27 to 2026-10-09 | All 14 backtests completed |

Actual-history results after assumed 10bps fees and 5bps slippage: 10 setups ended below starting equity, one above it (liquidity sweep), three produced no fills. This is a short single-market sample with fixed 0.01 quantity and $100,000 starting cash, not a profitability certificate or portfolio allocation recommendation. Three no-trigger strategies do not have execution coverage from this sample. No walk-forward/out-of-sample study was completed.

Detailed results and source candles: `artifacts/governance/real_market_strategy_backtests.json`. Synthetic scenarios: `artifacts/governance/full_feature_backtest_matrix.json`. Re-run using `PYTHONPATH=. .venv/bin/python scripts/audit/real_market_backtests.py` and `scripts/audit/synthetic_backtest_matrix.py`. Fresh market runs may differ; the saved source candles preserve the audited sample.

## Defects corrected

- Missing broker values now show unavailable instead of zero; offline API trading no longer appears AVAILABLE.
- Assistant risk status includes the local emergency lock.
- Unknown `/api/` requests return JSON 404 instead of SPA HTML 200.
- Voice startup failures show a recoverable message.
- Mobile navigation retains accessible names when labels are hidden; side selector and assistant close controls have explicit names.
- Cancelled polling clients no longer cause broken-pipe response tracebacks.

## External and implementation blockers

| Feature | State and remaining work |
|---|---|
| Windows / MT5 DEMO | Unverified here: Windows terminal, broker DEMO credentials, connection, preflight and broker-origin NO SEND/DEMO evidence required |
| Authenticated cloud AI | Keys absent; no authenticated provider calls verified |
| Redis / fleet SSE | Redis server unavailable; structured 503; fleet manifests do not prove running business services |
| Distributed API, DATA, AGENTS, NEWS, RISK, EXECUTOR roles | Passive handlers awaiting business wiring; heartbeat does not make them active |
| ML vote role | No trained/configured artifact; not active or live approved |
| Broker-dependent watchlist/positions/order fills | Not exercised with a populated real broker account |
| Microphone and speech output | Fallback/toggle tested; no physical microphone or audio output verification |
| Notifications | No delivery to another person/account performed; real delivery unverified |
| iPhone | 390px Chromium layout verified; actual Safari device, Tailscale and background uptime unverified |
| All markets / broker adapters | Not uniformly implemented or certified; crypto public candles do not validate FX/gold/MT5 execution |
| Live money | Remains locked; phases 11/15 broker-origin evidence and explicit live approval outstanding |

Repository doctor passes its software profile; that profile explicitly excludes live broker certification. Several static/reference research views are informational, not active distributed agents. The 11 browser cases cover the actions listed above, not every possible runtime state or physical device.

## Revalidation

```
.venv/bin/ruff check aura tests scripts/audit
.venv/bin/python -m pytest -q
npm --prefix dashboard run build
cd dashboard
AURA_TEST_PYTHON=<absolute-python> PLAYWRIGHT_CHROMIUM_EXECUTABLE=<absolute-chromium> npm run test:e2e
```
