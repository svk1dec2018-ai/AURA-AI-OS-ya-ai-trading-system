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
| 5 | PASS | Provider-neutral ingestion rejects invalid batches and measures data lag. |
| 6 | PASS | Backtest and paper execution share fill/cost semantics and causal guards. |
| 7 | PASS | Hypotheses and candidates are reproducible; overfit and untested candidates fail closed. |
| 8 | PASS | Retrieval is point-in-time, citation-bound, and external content has no command authority. |
| 9 | PASS | Ten registered specialist roles emit deterministic structured advisory evidence. |
| 10 | PASS | CEO evidence fusion is deterministic, contribution-traced, explainable, and advisory-only. |
| 11–15 | BLOCKED | Required phase-specific validation evidence has not yet been accepted. |

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

## Phase 5 evidence

- `artifacts/governance/data_quality_report.json`
- `artifacts/governance/anomaly_detection_logs.json`
- `artifacts/governance/phase_gate_status.json`

The market-data gate joins the existing normalization and candle-quality modules
behind a provider-neutral, fail-closed ingestion boundary. A batch is released
only when every record normalizes and the full series passes closed-candle,
ordering, duplicate, gap, future-data and staleness checks. Scanner and agent
decision services now require a quality gate, and accepted reports expose measured
latest-candle lag in milliseconds. Evidence uses deterministic internal fixtures;
it claims no external feed availability or live-market correctness.

```bash
python -m aura.ops.market_data_gate --write
python -m aura.ops.market_data_gate --check
```

## Phase 6 evidence

- `artifacts/governance/backtest_report.json`
- `artifacts/governance/bias_detection_report.json`
- `artifacts/governance/phase_gate_status.json`

The backtest gate moves the existing single- and multi-symbol engines onto the
same deterministic candle fill/cost model used by PaperBroker. Market, limit and
stop gap rules, adverse slippage, fees and contract multipliers therefore have one
implementation. Causal checks reject out-of-order/overlapping series and
future-dated strategy signals; orders created from a closed candle cannot fill on
that same candle. Evidence is a deterministic internal parity fixture, not a
strategy-performance, external-broker or live-readiness claim.

```bash
python -m aura.ops.backtest_gate --write
python -m aura.ops.backtest_gate --check
```

## Phase 7 evidence

- `artifacts/governance/strategy_evaluation_report.json`
- `artifacts/governance/phase_gate_status.json`

The strategy-research gate adds a canonical, provenance-bound hypothesis generator
to the existing bounded strategy factory. It exercises the existing conservative
fitness policy with stable and deliberately overfit internal fixtures, proves
candidate reproduction from identical inputs, and proves that lifecycle governance
rejects promotion without passed evidence. The report makes no market-performance
claim and performs no paper or live promotion.

```bash
python -m aura.ops.strategy_research_gate --write
python -m aura.ops.strategy_research_gate --check
```

## Phase 8 evidence

- `artifacts/governance/retrieval_benchmark_report.json`
- `artifacts/governance/phase_gate_status.json`

The knowledge/RAG gate connects the existing license-gated local ingestion and
trust firewall to one deterministic retrieval and citation-verification boundary.
It benchmarks known-answer retrieval and proves that future, low-trust, empty,
contradictory, and fabricated-citation evidence fails closed. Retrieved text is
always untrusted data with no owner-command or trading authority. The deterministic
fixture downloads or scrapes no external content.

```bash
python -m aura.ops.knowledge_rag_gate --write
python -m aura.ops.knowledge_rag_gate --check
```

## Phase 9 evidence

- `artifacts/governance/agent_consistency_report.json`
- `artifacts/governance/phase_gate_status.json`

The multi-agent gate adds a machine-readable registry for the existing ten-role
specialist desk. Every registration is advisory-only and explicitly lacks broker,
portfolio-mutation, strategy-approval, or execution authority. Two complete runs
over identical internal point-in-time context must emit identical structured
`AgentEvidence`; free-form output is isolated as an agent failure.

```bash
python -m aura.ops.multi_agent_gate --write
python -m aura.ops.multi_agent_gate --check
```

## Phase 10 evidence

- `artifacts/governance/decision_trace_logs.json`
- `artifacts/governance/phase_gate_status.json`

The CEO gate extends the existing deterministic aggregator with a structured trace
for every specialist contribution, trust/role/reliability weight, quorum threshold,
directional score, risk flag, support/opposition/abstention set, and explicit
decision reason. Identical semantic evidence produces the same content fingerprint
even when packet order changes. Missing quorum and excessive disagreement both
produce an explainable `FLAT` / no-trade decision. The CEO remains advisory-only
and cannot size a position, bypass risk, approve a strategy, or submit an order.

```bash
python -m aura.ops.ceo_decision_gate --write
python -m aura.ops.ceo_decision_gate --check
```

## Phase 11 readiness evidence (gate remains BLOCKED)

- `artifacts/governance/broker_evidence_readiness_report.json`

The readiness layer accepts only sealed, credential-free broker observations. It
checks causal timestamps, complete normalized fills, controlled-live mode,
verified environment identity, and at least three consecutive clean reconciliation
runs for each required adapter. A source label alone is not trusted: an explicitly
configured external attestation verifier must validate every bundle. Duplicate
captures, execution probes, and reconciliation runs are rejected rather than
counted twice.

This command performs no broker connection and grants no execution authority:

```bash
python -m aura.ops.broker_evidence_readiness --write
python -m aura.ops.broker_evidence_readiness --check
```

Phase 11 remains `BLOCKED`. Angel One is read-only, MT5 is demo-only, and no
accepted external fill/reconciliation evidence or separate financial-risk
authorization exists. Those facts cannot be manufactured by code-only tests.

### Offline evidence intake

Credential-free external exports can be assessed without granting the process
broker access. Each owner-controlled registry review is bound to the exact sealed
bundle SHA-256, requires at least two distinct reviewer fingerprints, and is itself
content-sealed. A reviewer fingerprint is an audit identifier, not a password or a
cryptographic signature; the registry must therefore be created and reviewed only
through the authenticated owner workflow.

```bash
python -m aura.ops.broker_evidence_intake \
  --evidence secure-import/angel-one-evidence.json \
  --evidence secure-import/mt5-evidence.json \
  --attestation-registry secure-import/owner-review-registry.json \
  --output runtime/reports/phase11-intake.json \
  --require-eligible
```

Successful intake means only `ELIGIBLE_FOR_GATE_REVIEW`. It does not update the
phase ledger, enable live money, connect to a broker, or count as owner trade
authorization. A blocked result exits with status 2 when `--require-eligible` is
used. Evidence and registry files must remain outside Git and secret storage must
not be included in either file.

### Evidence recorder integration contract

`BrokerEvidenceRecorder` converts the existing normalized `OrderState` and
`ReconciliationReport` objects into the sealed intake format. It accepts only
precomputed 64-character fingerprints for client order, broker order, broker
response, account and attestation identity. Raw identifiers, symbols, fill IDs,
prices and reconciliation details are never serialized into the evidence bundle;
reconciliation issue keys/details are represented only by one-way fingerprints.

The recorder accepts execution evidence only from a complete `FILLED` order and
rejects execution capture in `PAPER` or `READ_ONLY` mode. Duplicate execution and
reconciliation observations fail closed, including under concurrent recorder use.
It performs no broker call and does not verify that an external fingerprint is
authentic; the separate owner review/attestation workflow remains mandatory.

The audit uses Git's tracked plus non-ignored untracked file set, so tracked
packages such as `aura/runtime` remain visible even though runtime state directories
are generically ignored. Generated governance artifacts are excluded from their own
tree digest to prevent circular hashes.

## Safety boundary

Phase 15 cannot be manufactured from code-only tests or historical data. Broker
execution evidence, reconciliation stability, long-duration forward validation,
incident-free operation, risk certification, and explicit human live approval are
external facts that remain required. Until then, live deployment stays blocked.
