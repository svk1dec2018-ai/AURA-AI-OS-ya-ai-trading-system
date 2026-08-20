# AURA mandatory phase gates

AURA development and live readiness are governed by the canonical Phase 0–15
contracts in `aura.ops.phase_gates`. A phase is never complete merely because code
for it exists. It is complete only when every required validation output is
present, content-addressed, and the sequential ledger records `PASS`.

## Enforcement

- A later phase cannot pass unless the immediately preceding phase is `PASS`.
- Every `PASS` record requires all validation outputs named in its canonical spec.
- Evidence files are bound to their SHA-256 digests. Missing or changed evidence
  invalidates the ledger.
- `FAIL` and `BLOCKED` records require explicit reasons.
- LIVE preflight requires a valid ledger with Phase 15 `PASS`, in addition to the
  existing immutable-strategy, human-approval, broker-evidence, health, and risk
  controls.
- Paper, demo, research, and shadow modes remain non-live and cannot use a phase
  ledger to acquire live authority.

## Current truthful status

| Phase | Gate | Meaning |
|---:|---|---|
| 0 | PASS | Repository baseline is fully inventoried by generated evidence. |
| 1 | PASS | Six mandatory core entities have strict schemas and canonical, versioned serialization evidence. |
| 2 | PASS | Order lifecycle, restart recovery, and fail-closed reconciliation have deterministic evidence. |
| 3 | PASS | Risk veto, stop-distance sizing, exposure controls, stress overlays, and kill-switch behavior have deterministic evidence. |
| 4 | PASS | Broker capabilities, common-interface conformance, reconciliation support, and strategy isolation have deterministic evidence. |
| 5–15 | BLOCKED | Required phase-specific validation evidence has not yet been accepted. |

Existing code in later-phase areas is preserved and classified, but its presence
does not retroactively pass a gate. The generated
`artifacts/governance/phase_gate_status.json` is the machine-readable source of
truth.

## Phase 0 evidence

- `artifacts/governance/repo_audit.json`
- `artifacts/governance/module_map.md`
- `artifacts/governance/test_inventory.json`
- `artifacts/governance/phase_gate_status.json`

Regenerate and verify it with:

```bash
python -m aura.ops.repository_audit --write
python -m aura.ops.repository_audit --check
```

## Phase 1 evidence

- `artifacts/governance/core_contract_schema_report.json`
- `artifacts/governance/core_contract_validation_suite.json`
- `artifacts/governance/phase_gate_status.json`

The contract suite covers Tick, Candle, Order, Fill, Position, and Portfolio. It
verifies strict unknown-field rejection, timezone and order-price semantics, and
canonical round trips through a versioned JSON envelope. Regenerate and verify the
sequential evidence with:

```bash
python -m aura.ops.repository_audit --write
python -m aura.ops.core_contracts --write
python -m aura.ops.repository_audit --check
python -m aura.ops.core_contracts --check
```

Phase 1 is a data-contract gate only. It grants no broker, deployment, or live-money
authority.

## Phase 2 evidence

- `artifacts/governance/state_transition_logs.json`
- `artifacts/governance/reconciliation_test_report.json`
- `artifacts/governance/phase_gate_status.json`

The state gate validates acknowledged and expired order states, immutable terminal
states, WAL replay, checkpoint-plus-tail restart recovery, clean reconciliation,
and fail-closed mismatch detection using explicit internal fixtures. It does not
claim external broker validation or grant live-money authority. Regenerate it after
Phase 0 and Phase 1 evidence:

```bash
python -m aura.ops.state_engine_gate --write
python -m aura.ops.state_engine_gate --check
```

## Phase 3 evidence

- `artifacts/governance/risk_stress_test_report.json`
- `artifacts/governance/risk_violation_simulation_logs.json`
- `artifacts/governance/phase_gate_status.json`

The hard risk gate validates deterministic stop-distance sizing, daily-loss and
drawdown vetoes, gross/symbol exposure caps, statistical stress vetoes, and the
global kill switch. It explicitly proves that risk-reducing orders remain possible
while new risk is frozen. Fixtures are internal deterministic simulations, not
market or broker claims, and grant no live-money authority.

```bash
python -m aura.ops.risk_engine_gate --write
python -m aura.ops.risk_engine_gate --check
```

## Phase 4 evidence

- `artifacts/governance/broker_adapter_conformance_report.json`
- `artifacts/governance/phase_gate_status.json`

The broker gate declares machine-readable capabilities for Paper, Angel One
read-only, MT5 demo, and Dhan sandbox adapters. It verifies their common contract,
proves the strategy package has no broker/SDK imports, and explicitly records when
an adapter does not support reconciliation. This code-only gate claims no
credential-backed order execution and enables no live money.

```bash
python -m aura.ops.broker_conformance_gate --write
python -m aura.ops.broker_conformance_gate --check
```

The audit uses Git's tracked plus non-ignored untracked file set, so tracked
packages such as `aura/runtime` remain visible even though runtime state directories
are generically ignored. Generated governance artifacts are excluded from their own
tree digest to prevent circular hashes.

## Safety boundary

Phase 15 cannot be manufactured from code-only tests or historical data. Broker
execution evidence, reconciliation stability, long-duration forward validation,
incident-free operation, risk certification, and explicit human live approval are
external facts that remain required. Until then, live deployment stays blocked.
