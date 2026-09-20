# Contributing to AURA AI OS

AURA is financial decision infrastructure. Correctness, reproducibility and fail-closed behavior take priority over feature count.

## Development workflow

1. Branch from current `main`.
2. Keep one coherent change per pull request.
3. Do not put credentials, broker sessions, account secrets or private data in source, tests, issues or screenshots.
4. Run the same gates as CI before requesting review:

```bash
python -m pip install -e ".[dev]"
python -m pip check
ruff check aura tests examples
pytest -q
python -m build
cd dashboard
npm ci --no-audit --no-fund
npm run typecheck
npm run build
```

For runtime changes, verify backend, dashboard proxy, Redis/fleet and fail-closed MT5 behavior. CI contains Linux runtime-smoke and Windows smoke jobs for these paths.

## Financial authority rules

Strategy, research, AI and UI code must not directly submit broker orders. New exposure must continue through the governed decision -> RiskEngine -> approved broker adapter path.

Do not:
- bypass kill switches or risk limits
- enable real money by default
- fabricate broker/market evidence
- weaken reconciliation or WAL integrity
- add withdrawal/fund-transfer authority
- promote a strategy automatically to unrestricted live execution

## UI contributions

Preserve truthful states. Missing market data must display unavailable/degraded rather than invented values. Keep chart, positions, P&L, risk and execution status visually distinguishable.

AURA's dashboard is independently implemented. Do not copy source from GPL/AGPL projects into the dashboard.

## Pull requests

Explain:
- problem being solved
- files/components changed
- user-visible behavior
- safety impact
- validation performed
- external blockers that remain

A green unit-test suite is not sufficient for startup/runtime changes; the runtime-smoke jobs must also pass.
