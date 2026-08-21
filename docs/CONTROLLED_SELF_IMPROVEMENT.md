# AURA controlled self-improvement and owner authority

AURA now contains an optional OpenAI-powered maintenance developer plus a deterministic
authority, sandbox, audit and correction plane. This is real code-change capability, not an
LLM chat prompt with unrestricted shell access.

The implementation deliberately separates four things:

1. **Observe and diagnose** — deterministic health state becomes a typed incident.
2. **Propose** — an OpenAI Responses API model returns a strict repair plan and unified diff.
3. **Validate** — the diff is applied to a temporary copy containing only files tracked at the
   proposal's exact base commit. Credentials are removed and only host-configured test commands
   run; commands proposed by the model are never executed.
4. **Approve and apply** — an owner receipt is bound to the base commit, patch hash and passing
   validation. The exact patch may then modify a clean development worktree. It is not committed,
   pushed, merged, deployed or granted financial authority automatically.

The state machine is:

```text
health incident
  -> OpenAI repair proposal
  -> patch/path/fund-operation policy validation
  -> credential-free sandbox + allowlisted tests
  -> exact owner approval receipt
  -> development worktree apply
  -> PR-ready review
  -> normal CI/security/release governance
```

Every transition is recorded in a checksummed, append-only WAL and is replayed on restart. A
truncated, reordered or tampered journal fails closed.

## Authority model

| Capability | Maintenance AI | Developer | Owner |
|---|---:|---:|---:|
| Read/monitor/diagnose | Yes | Yes | Yes |
| Propose a code diff | Yes | Yes | Yes |
| Run fixed sandbox checks | Yes | Yes | Yes |
| Apply an owner-approved patch to a clean development branch | No | Yes | Yes |
| Approve exact code patch | No | No | Yes |
| Request an audited financial reporting correction | Yes | Yes | Yes |
| Approve an exact financial reporting correction | No | No | Yes |
| Request a separately governed live action | No | Yes | Yes |
| Add, withdraw or transfer funds | **No** | **No** | **No** |
| Rewrite historical fills/trades/P&L in place | **No** | **No** | **No** |
| Bypass risk, expose secrets or self-approve live deployment | **No** | **No** | **No** |

The machine-readable matrix is `aura.maintenance.authority.DevelopmentAuthorityPolicy`.
Guard code, secret files, runtime financial state and CI workflow files cannot be changed by the
automatic patch applier. Risk, execution, portfolio and persistence changes are classified as
`FINANCIAL_CORE` and need an additional explicit owner acknowledgement.

## OpenAI integration

`aura.ai.openai_responses.OpenAIResponsesClient` uses the official HTTPS Responses API with
strict JSON-schema output and `store=false`. The endpoint is fixed to OpenAI; an environment
override cannot redirect the API key to another host. Raw hidden reasoning and Authorization
headers are neither returned nor journaled.

OpenAI models may join the normal AURA trading council by setting `AURA_OPENAI_MODELS`. Their
output is advisory `AgentEvidence`; they receive no broker methods and cannot bypass the CEO,
risk engine, order state machine or deployment gates.

Create `.env.local` from `.env.example` and supply the key on the host. `.env.local` is ignored by
Git. A ChatGPT subscription is not used as an application credential; AURA uses an OpenAI API key
owned by the operator.

```bash
cp .env.example .env.local
# securely set OPENAI_API_KEY in .env.local
python -m pip install -e '.[dev]'
```

Official API references used by this implementation:

- <https://developers.openai.com/api/docs/guides/structured-outputs>
- <https://developers.openai.com/api/docs/guides/function-calling>
- <https://developers.openai.com/api/docs/guides/migrate-to-responses>

## Operator commands

Inspect immutable authority:

```bash
aura-maintenance policy
```

Run credential-free quick health checks:

```bash
aura-maintenance probe --repository .
```

Create and fully sandbox-test a repair proposal from selected tracked files:

```bash
aura-maintenance propose \
  --repository . \
  --component market_data \
  --severity DEGRADED \
  --summary "stale-feed recovery test is failing" \
  --source aura/data/live_plane.py \
  --source tests/test_live_data_plane.py
```

The result prints a proposal ID and SHA-256 patch digest. Review the proposal and exact digest,
then apply only that validated patch:

```bash
aura-maintenance approve-apply \
  --repository . \
  --proposal-id 'change:...' \
  --expected-patch-sha256 '...' \
  --owner-id primary-owner
```

For `FINANCIAL_CORE` code, add `--ack-financial-core`. The command still only changes a clean
development worktree; normal review, commit, PR, CI and deployment remain separate.

## P&L and trade corrections

Broker fills, orders, cash, positions and original ledger P&L are immutable facts. AURA supports
owner-approved compensating **reporting corrections** through
`AuditedFinancialCorrectionLedger`:

- trade annotation;
- net realized-P&L adjustment;
- fee adjustment with exact P&L relationship;
- broker trade correction bound to evidence and reconciliation.

Controlled-live corrections require an evidence SHA-256 and reconciliation ID. The schema has no
cash, deposit, withdrawal, transfer or position-quantity field.

```bash
aura-maintenance correction-request \
  --mode PAPER \
  --kind PNL_ADJUSTMENT \
  --pnl-delta=-3.50 \
  --reason "correct paper reporting rounding discrepancy" \
  --requester primary-owner

aura-maintenance correction-approve \
  --correction-id 'correction:...' \
  --expected-content-sha256 '...' \
  --owner-id primary-owner

aura-maintenance correction-view \
  --base-realized-pnl 1000 \
  --base-fees-paid 25
```

The corrected view never mutates the source portfolio ledger or broker reconciliation state.

## Honest boundaries

- The maintenance AI does not automatically merge or deploy its own code.
- The file sandbox strips credentials, but network isolation must also be enforced by the host or
  container policy for high-assurance deployment.
- OpenAI calls require API access and may incur operator account charges.
- A passing code repair does not make Phase 11 pass and does not enable live money. Authentic
  broker-origin evidence, clean reconciliation history, operational validation and separate
  financial-risk authorization remain external gates.
