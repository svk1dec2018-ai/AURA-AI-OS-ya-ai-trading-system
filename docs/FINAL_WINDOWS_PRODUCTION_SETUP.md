# AURA AI OS — Final Windows Production Setup

This is the canonical beginner setup for the current AURA release.

## What this release is ready for

AURA is software-production-ready for unattended paper/demo operation when the final doctor passes.

It includes:
- premium local dashboard
- MT5 DEMO integration and broker preflight
- deterministic RiskEngine and kill switch
- durable WAL/checkpoints and reconciliation
- multi-agent/CEO decision stack
- strategy research and self-evolution in governed paper/demo mode
- nine-service Redis fleet with restart supervisor
- live SSE health/event stream
- all-market provider registry
- CodeQL, Python 3.11/3.12 CI, dashboard production build and container build

Real-money execution is intentionally not auto-enabled. Phases 11 and 15 require broker-origin forward evidence and explicit human authorization.

## First-time setup

1. Sync/pull the latest `main` branch.
2. Double-click:

   `FINAL_SETUP_AURA.cmd`

The setup will:
- create/update `.venv`
- install AURA dev, Redis/distributed and MT5 dependencies
- install Node.js LTS when missing
- install Docker Desktop when winget is available and Docker is missing
- create `.env.local` from `.env.example` without overwriting an existing private config
- install dashboard packages
- build the production dashboard
- run `pip check`, Ruff, pytest and Python distribution build
- run the AURA final production doctor

Docker Desktop may require one Windows logout/restart after first installation.

## Configure credentials safely

Double-click:

`CONFIGURE_AURA.cmd`

It opens the private `.env.local` file. That file is gitignored.

For the first MT5 DEMO deployment, set only:

```text
AURA_MT5_DEMO_LOGIN=your_demo_login
AURA_MT5_DEMO_PASSWORD=your_demo_password
AURA_MT5_DEMO_SERVER=your_demo_server
AURA_MT5_TERMINAL_PATH=
```

Keep these blank:

```text
AURA_HUMAN_LIVE_APPROVAL_ID=
AURA_LIVE_TRADING_ENABLED=
```

Do not paste secrets into GitHub issues, screenshots, chat messages or source files.

Optional provider credentials can be added later:
- Dhan: `AURA_DHAN_CLIENT_ID`, `AURA_DHAN_ACCESS_TOKEN`
- Angel One: API/client/session token fields from the template
- OANDA: account ID/access token
- Binance/Kraken: authenticated connector fields when those execution adapters are formally validated
- Telegram: bot token/chat ID
- OpenAI: optional advisory AI only; not required for the deterministic trading core

## Before every start

1. Open Docker Desktop and wait until Docker Engine is ready.
2. Open MetaTrader 5.
3. Log in to the DEMO account configured in `.env.local`.
4. Confirm MT5 shows a live connection.

## Start the complete stack

Double-click:

`START_AURA_PRODUCTION.cmd`

This starts:
- Redis
- the nine AURA fleet services
- fleet restart supervisor
- AURA backend on `127.0.0.1:8766`
- premium dashboard on `127.0.0.1:3100`
- strict all-market production doctor

The doctor also performs a real read-only MT5 DEMO broker preflight on Windows:
- terminal connected
- DEMO guard verified
- tradable symbols discovered
- market clock is point-in-time safe

The starter fails closed if the live-risk acknowledgement is enabled.

## Verify

Double-click:

`AURA_PRODUCTION_DOCTOR.cmd`

Expected paper/demo result:

```text
Software production ready: YES
Live-money eligible: NO
```

That is the correct state until broker-origin live-readiness evidence exists.

In the dashboard check:
- System Health
- Distributed Fleet
- MT5 live terminal
- Risk Center
- strategy/AI decision surfaces
- positions/orders
- journal and diagnostics

## Start AURA DEMO trading

Use the dashboard's protected DEMO start only after the MT5 checks are green.

AURA performs the broker-side no-send `order_check` readiness probe before the autonomous DEMO runtime starts. The account must pass the DEMO guard.

## Stop

Double-click:

`STOP_AURA_PRODUCTION.cmd`

It stops the fleet, Redis runtime and AURA dashboard/backend. It does not close MetaTrader 5 itself.

## Logs

Dashboard/backend logs:
- `runtime/aura2_dashboard/backend.out.log`
- `runtime/aura2_dashboard/backend.err.log`
- `runtime/aura2_dashboard/dashboard.out.log`
- `runtime/aura2_dashboard/dashboard.err.log`

Fleet logs:
- `runtime/fleet/supervisor.out.log`
- `runtime/fleet/supervisor.err.log`
- one log per fleet service under `runtime/fleet/`

## Live-money boundary

Do not manually bypass the phase ledger or edit code to force LIVE mode.

Current governance requires:
- broker integration Phase 11 PASS
- controlled-live Phase 15 PASS
- immutable APPROVED strategy
- broker-origin forward evidence
- minimum release-gate metrics
- zero unresolved critical/reconciliation/data-integrity incidents
- explicit human live approval
- exact live-risk acknowledgement
- smallest-size canary first

Passing software tests, backtests or AI confidence does not establish profitability or live eligibility.
