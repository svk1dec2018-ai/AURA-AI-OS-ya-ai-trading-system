# AURA AI OS client handoff

## Release classification

This repository is a validated **paper/demo research release candidate**. It is
not certified for unrestricted live-money trading. Live authority remains
fail-closed behind the sequential Phase 0–15 ledger, broker-origin forward
evidence, an immutable approved strategy, an independent risk veto, and explicit
human approval.

## Included in this release candidate

- broker-neutral financial contracts, order state, portfolio ledger and risk controls
- paper execution, durable WAL/checkpoints and reconciliation foundations
- multi-market data quality, point-in-time and closed-candle protections
- specialist agents, deterministic CEO evidence fusion and AI authority limits
- knowledge firewall and trusted point-in-time intelligence inputs
- causal backtesting, purged walk-forward and block-bootstrap Monte Carlo checks
- sealed one-use holdouts, parameter-stability and regime validation
- corporate-action adjustments, futures-roll provenance and option-chain replay
- durable paper evidence, shadow outcomes, strategy governance and restart-safe learning
- deterministic, content-addressed research manifests
- Phase 0 repository governance and a fail-closed live preflight

## Verified commands

Run from the repository root with Python 3.11 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
ruff check .
pytest -q
python -m compileall -q aura
python -m build
python -m aura.ops.repository_audit --check
python examples/run_production_preflight.py --mode paper --connector public
```

The public paper preflight must report `"ready": true` while
`live-money-disabled` remains passed.

## Safe client demonstration

No broker credential is needed for the public-data research path:

```bash
python examples/run_public_crypto_live.py
python examples/run_free_public_strategy_lab.py
```

Optional local AI council support uses Ollama and remains advisory. AI output
cannot set leverage, quantity, risk limits, broker permission or live authority.

## Credential-backed paper/demo modes

- MT5 requires a verified demo account and the `mt5_demo` preflight profile.
- Dhan uses live Indian-market data with internal paper execution and requires
  user-owned Dhan credentials supplied only through environment variables.
- Shoonya, Flattrade and OANDA profiles are read-only/data-oriented unless an
  independently validated broker execution adapter is explicitly approved.

Never commit `.env`, API keys, passwords, TOTP seeds, access tokens or broker
sessions. No third-party credential is included in this release.

## External acceptance work that code cannot fabricate

Live certification requires real elapsed-time and broker-origin evidence:

1. all sequential phase gates must pass with content-addressed evidence;
2. broker-specific rejection, partial-fill, reconnect and reconciliation tests;
3. venue margin, lot, tick, expiry and settlement validation;
4. forward paper/demo operation across trend, chop, volatility and news regimes;
5. zero unresolved critical, reconciliation or data-integrity incidents;
6. immutable strategy promotion to `PAPER_VALIDATED`, followed by explicit human approval;
7. a smallest-size live canary only after the production release gate passes.

Until those facts exist, the correct client claim is **paper/demo research release
candidate**, not guaranteed-profit or unrestricted-live production software.
