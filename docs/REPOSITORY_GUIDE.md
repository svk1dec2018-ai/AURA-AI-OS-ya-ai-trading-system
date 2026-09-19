# AURA repository guide

## Canonical operator entry points

For a normal Windows MT5 DEMO installation, these are the supported root entry points:

| Purpose | File |
|---|---|
| First installation + verification | `FINAL_SETUP_AURA.cmd` |
| Edit private configuration | `CONFIGURE_AURA.cmd` |
| Optional local Ollama models | `INSTALL_FREE_UNLIMITED_AI.cmd` |
| Start complete paper/demo stack | `START_AURA_PRODUCTION.cmd` |
| Verify running stack | `AURA_PRODUCTION_DOCTOR.cmd` |
| Stop complete stack | `STOP_AURA_PRODUCTION.cmd` |

Other root launchers remain for compatibility, development, diagnostics or narrower workflows. They are not the canonical production path.

## Source layout

- `aura/domain` — canonical financial data contracts
- `aura/data` — market-data adapters and quality controls
- `aura/agents` — deterministic/AI specialist evidence and CEO synthesis
- `aura/risk` — independent financial risk authority
- `aura/execution` — broker abstractions, order state, reconciliation
- `aura/persistence` — WAL, checkpoints and recovery
- `aura/research`, `aura/evolution` — bounded strategy research/learning
- `aura/fleet` — Redis event transport and distributed service supervision
- `aura/webapp` — local owner API/backend
- `dashboard` — Next.js owner terminal
- `tests` — deterministic regression suite
- `artifacts/governance` — generated phase-gate evidence
- `docs` — operator, architecture and governance documentation

## Runtime ports

- 3100 — Next.js owner dashboard
- 8766 — AURA owner backend/API
- 6379 — local Redis
- 9100–9108 — fleet health endpoints

All normal owner interfaces bind to loopback/local services. Real-money authority remains externally gated.
