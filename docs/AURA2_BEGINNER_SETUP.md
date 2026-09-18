# AURA 2 Beginner Setup — Windows + MT5 DEMO

This guide is for an owner who does not know coding. You normally do not need PowerShell or manual commands.

## What AURA 2 runs

AURA 2 uses two local services on your Windows computer:

- AURA Python/MT5 backend: http://127.0.0.1:8766
- Premium AURA 2 dashboard: http://127.0.0.1:3100

MetaTrader 5 itself stays open on Windows. AURA connects to the already logged-in MT5 DEMO session.

The dashboard is local-first. The current release keeps unrestricted real-money trading locked. Fund transfer and withdrawal are not exposed.

## Before the first start

1. Install MetaTrader 5 from your broker or MetaQuotes.
2. Open MetaTrader 5.
3. Log in to a DEMO account.
4. Confirm MT5 shows an active connection and live prices.
5. Keep MT5 open.
6. Keep internet available during the first AURA 2 start because Python/Node packages may need to be installed.

## Start AURA 2

1. Open the AURA repository folder in Windows File Explorer.
2. Find `START_AURA2.cmd`.
3. Double-click `START_AURA2.cmd`.
4. Windows may ask for permission while winget installs Python or Node.js on the first run. Allow the normal package installation.
5. The launcher creates/updates AURA's private `.venv`, installs the official MetaTrader5 Python bridge, installs dashboard packages on the first run, and starts both local services.
6. When ready, the browser opens automatically at:

   http://127.0.0.1:3100

The launcher intentionally does **not** auto-start trading.

## Verify the dashboard before starting DEMO trading

In AURA 2:

1. Open **System Health**.
2. Confirm the backend loads and the readiness checks do not show a connection error.
3. Open **Live Charts**.
4. Keep symbol `XAUUSD` or enter the exact symbol used by your broker.
5. Select M1, M5, M15, M30, H1, H4 or D1.
6. Confirm candles load.
7. Confirm BID / ASK / spread updates. These quotes are read-only dashboard data.
8. Open **Risk Center** and review the safety/readiness checks.

If your broker uses a suffix such as `XAUUSDm`, AURA attempts to resolve the broker symbol automatically.

## Start protected MT5 DEMO trading

Only after MT5 and the dashboard look healthy:

1. Go to **Overview** or **Trading Desk**.
2. Click **Start AURA DEMO** / **Start continuous DEMO**.
3. AURA performs MT5 DEMO preflight and a broker `order_check` readiness test before the autonomous runtime starts.
4. AURA then follows the governed chain:

   market data -> agents -> CEO -> independent RiskEngine -> protected MT5 DEMO execution -> reconciliation -> learning

5. Watch:
   - **Live Charts** for broker candles/quotes
   - **Opportunities** for ranked decisions
   - **AI Brain** for CEO evidence
   - **Agent Debate** for Bull/Bear/Counterfactual review
   - **Risk Center** for hard gates
   - **Portfolio** for measured account/portfolio state
   - **Learning** for replay/challenger state
   - **System Health** for runtime status and logs

## AURA/JARVIS assistant

Click **AURA** at the top-right or open **Owner / JARVIS**.

Example questions:

- Gold analyse karo
- Aaj ka P&L dikhao
- Latest opportunities batao
- Last trade kyu skip hua?
- Agent debate explain karo
- System health check karo

The assistant is governed by the same AURA authority model. It cannot bypass RiskEngine or unlock fund movement.

## Stop safely

Recommended order:

1. In the dashboard, click **Stop runtime**.
2. Confirm the engine shows STOPPED.
3. Close the browser if you want.
4. Double-click `STOP_AURA2.cmd`.
5. You may then close MetaTrader 5.

`STOP_AURA2.cmd` stops the AURA backend/dashboard processes recorded by the launcher. It does not close MT5 itself.

## Emergency stop

Use **Emergency Lock** in AURA 2 if you want AURA to stop its DEMO runtime and block restart until the local lock is reset.

The independent financial RiskEngine may also refuse new risk separately.

## If AURA 2 does not open

First keep MT5 open and retry `START_AURA2.cmd`.

If it still fails, send the exact screen/error plus these files if they exist:

- `runtime\aura2_dashboard\backend.err.log`
- `runtime\aura2_dashboard\dashboard.err.log`
- `runtime\aura2_dashboard\backend.out.log`
- `runtime\aura2_dashboard\dashboard.out.log`

Do not send passwords, API keys, MT5 passwords, tokens or recovery codes.

## What automated CI proves

The repository CI validates Python 3.11/3.12, governance gates, Ruff, the full pytest suite, production preflight, Python package build, Next.js TypeScript typecheck, Next.js production build, Docker build and CodeQL.

CI cannot prove your particular broker session, Windows MT5 installation, internet connection, broker symbol catalogue, future fills/rejects, or long-duration profitability. Those need forward DEMO operation on your actual machine/account.

## 24/7 later

For 24/7 operation, use the same architecture on a Windows VPS:

- Windows VPS
- MetaTrader 5 logged into DEMO/approved broker account
- native AURA Python backend
- AURA 2 Next.js dashboard
- optional local research/AI services

Complete forward evidence should be collected before considering any controlled real-money canary.
