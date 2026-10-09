# AURA Prime handoff — 9 October 2026

This package combines the existing `aura-prime-rebuild` code at `f334196`
with the later free-provider changes from the original AURA repository and
the setup/runtime corrections in this release. It preserves the existing
financial core. It does not certify profitability or real-money execution.

## Start on Windows

Extract this package into a **new folder**, for example
`C:\Users\opc\Documents\AURA-Prime`. Keep your earlier project as a backup.

1. Double-click `AURA_PRIME.cmd` and choose **1 — Setup**.
2. Choose **5 — Configure**. Select **2 — MT5 DEMO** and enter the DEMO
   account login, password and exact server. The terminal path can remain blank
   when the installed terminal can be discovered.
3. Optional AI: select **G** for Groq, **8** for OpenRouter, **N** for NVIDIA,
   **M** for Gemini, or **1** for a running local OmniRoute/Ollama service.
   Broker credentials and API keys are stored only in the private `.env.local`.
4. Open MetaTrader 5 and log in to that DEMO account. Enable terminal algorithmic
   trading if it is disabled. Confirm the terminal has fresh prices.
5. Choose **2 — Start**. Open `http://127.0.0.1:3100`.
6. Choose **3 — Doctor**. This stricter check requires the MT5 bridge,
   account credentials and a connected DEMO terminal. Fix any reported failure.
7. In the dashboard choose **START DEMO**. Its preflight verifies DEMO account
   mode, tradable instruments, timestamps and a broker `order_check` before
   starting the autonomous runtime. Do not expect orders when no setup passes
   the independent risk and market-data checks.
8. Use **STOP** or **EMERGENCY LOCK** in the dashboard. Console option **6**
   closes AURA's own processes while leaving MT5 open.

An MT5 account uses a login/password/server, **not an API key**. An LLM key
alone cannot connect MT5 or make broker execution ready. No paid OpenAI key
is needed. Cloud free tiers retain their quotas and availability limits.

## What changed

- Migrated the existing staged Prime implementation into the release checkout;
  `aura-prime` on GitHub currently contains only its bootstrap README.
- Default startup is local; Docker/Redis is optional.
- Rebuilt all deterministic software evidence during setup, rather than leaving
  schema/governance evidence stale after dependency or source changes.
- Supported auditing an extracted source ZIP without a `.git` directory,
  while excluding private environment files and runtime output.
- Preserved existing environment values and added Groq/NVIDIA/Gemini wizard options.
- Connected OmniRoute-compatible reasoning to the advisory council, alongside
  the existing free cloud routes and failover.
- Exposed configuration status without claiming API connection verification.
- Made `prime-ui` check dashboard readiness separately from strict broker readiness.
- Applied the broker-resolved chart symbol correction.
- Made Redis failures return structured unavailability instead of crashing SSE.
- Added session token controls and a `/workstation` route for the existing strategy,
  backtest, portfolio, journal, learning and diagnostics workflows.
- Improved mobile chart order/readability. Missing metrics remain unavailable.
- Avoided reinstalling backend dependencies on every start; reused current builds.
- Restricted process shutdown to commands belonging to this project.
- Added real-browser smoke tests and corresponding CI steps.

## Validation and limits

See `artifacts/governance/release_validation.json` for observed results. Software test cases and
generated governance evidence are not broker-origin fills or a live trial.

| Area | Release state |
| --- | --- |
| Python software suite, schema/risk/execution/recovery checks | Tested locally |
| Dashboard TypeScript and production build | Tested locally |
| Backend API proxy, cockpit, mobile view, owner token and guarded start | Tested locally |
| Blank broker credentials | Dashboard opens; trading stays blocked |
| Actual Windows terminal/MT5 DEMO fills and reconciliation | Requires the owner's Windows terminal and DEMO account; not verified here |
| Cloud AI authenticated calls | Keys intentionally absent; not verified here |
| India/OANDA feeds | Credentials/account permissions required; data support does not imply order support |
| Binance/Kraken authenticated auto execution | Not certified by this release; public data support is separate |
| Redis distributed business pipeline | Optional infrastructure; several roles remain passive pending explicit business wiring |
| ML models | Optional research capabilities; no trained live-approved model is supplied |
| Real-money release | Phases 11/15 remain blocked pending broker-origin evidence and approval |
| GitHub publication/Actions on this exact release | Blocked by target-repository integration permissions (403) |

The wider all-market/autonomous-development roadmap is **not fully completed**.
This release is an improved local DEMO candidate; it must not be described as
“only API keys remaining for unrestricted real-money trading.”

## GitHub publication blocker

The connected app can read the source repository, but the target `aura-prime`
write request returned **403: Resource not accessible by integration**.
Its GitHub app installation uses **selected repositories**.

Open `https://github.com/settings/installations/154236705`, select the
`svk1dec2018-ai/aura-prime` repository in that installation, and save. This
is repository access configuration; do not share a GitHub token in chat.
GitHub account suspension status was not established by this permission error.

After access is fixed, the migration and corrections can be published as a
reviewable commit/PR and GitHub Actions can validate Windows smoke checks.

## Troubleshooting

- Dashboard does not open: inspect `runtime/aura2_dashboard/backend.err.log`
  and `dashboard.err.log`; use console option **4 — Repair**.
- Missing provider: configure only the relevant credential group, then stop
  and restart AURA so the process loads the updated `.env.local`.
- Symbol suffix: AURA requests `XAUUSD` and displays the exact broker-resolved
  instrument when available. Do not invent a symbol spelling; check Market Watch.
- MT5 offline: check DEMO server/account, terminal connection and fresh ticks.
- Broker start rejected: use Doctor and the dashboard diagnostics; do not
  weaken clock, risk, account-mode or reconciliation controls.
- Owner token required: enter `AURA_OWNER_TOKEN` in the System panel for this
  browser session. API/broker keys belong in the private credential wizard.
- Full tools: open Research -> full workstation, or visit `/workstation`.

## Developer checks

```text
python -m pip install -e ".[dev,distributed,analytics,observability]"
python -m aura.ops.refresh_software_evidence
ruff check aura tests examples
pytest
python -m build
```

From `dashboard`, run `npm ci`, `npm run typecheck`, `npm run build`,
`npx playwright install chromium`, then `npm run test:e2e`. Set
`AURA_TEST_PYTHON` to the Python interpreter where AURA is installed.
The browser tests require blank broker credentials and no already-running AURA
process on the test ports. They exercise real local endpoints without broker fills.
