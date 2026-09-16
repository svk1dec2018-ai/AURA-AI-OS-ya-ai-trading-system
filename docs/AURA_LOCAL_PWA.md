# AURA AI OS — Local Web App / PWA

This is the beginner-facing control panel for the existing AURA engine. It does not replace the scanner, agents, RiskEngine, execution engine, learning runtime, or MT5 DEMO protection already in the repository.

## What it does

- Runs locally at `http://127.0.0.1:8765`.
- Can be installed from a supporting browser as an app/PWA.
- Reads the existing `runtime/mt5_autonomous_demo/status.json` state.
- Shows account identity (masked in the UI), equity, drawdown, scanner opportunities, broker DEMO orders/fills, runtime counters, system mode, risk kill state, and log output.
- Starts the existing `aura.ops.mt5_autonomous_demo` runtime.
- Stops the AURA child runtime from the UI.
- Provides an app-level emergency lock that stops the child runtime and prevents restart until explicitly reset.

## Safety boundary

The first web release is intentionally local and DEMO-only:

- The HTTP server binds only to `127.0.0.1`.
- The browser UI never accepts or stores an MT5 password.
- AURA reuses the MT5 terminal session already logged in on the PC.
- The existing broker guard still rejects non-DEMO MT5 accounts before broker execution.
- Real-money execution, withdrawals, and fund transfers remain disabled in this control panel.
- Closing the local AURA web server stops the child AURA runtime so an unseen background trading process is not deliberately left running by the app.

## Beginner start

1. Pull the latest repository version.
2. Open MetaTrader 5 and log in to the intended **DEMO** account.
3. Double-click `START_AURA_APP.cmd`.
4. The browser opens AURA automatically.
5. Leave the defaults (`10` symbols, `100` closed-candle batches) for the first run.
6. Press **Start AURA**.
7. Watch runtime status, opportunities, orders/fills, risk state, and logs from the dashboard.
8. Use **Stop AURA** for a normal stop.
9. Use **Emergency lock** when you want to stop the child runtime and prevent an accidental restart. Use **Reset lock** only when you intentionally want to enable starting again.

## Install as an app

When Chrome/Edge offers **Install AURA AI OS**, use that option. The installed PWA still talks to the local AURA server, so `START_AURA_APP.cmd` (or a future Windows auto-start service) must be running.

## Current scope

This first release is the local control surface. Later UI phases can add richer charting, persistent trade-history views, AI chat/voice controls, agent-by-agent visualisation, notification routing, desktop auto-start, and authenticated remote/mobile access without changing the existing trading engine.
