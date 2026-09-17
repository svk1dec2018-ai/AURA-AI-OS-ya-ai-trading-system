# AURA owner completion prompt and acceptance contract

Source: owner's requirements supplied in this task, 2026-09-17. Historical
conversation previews are context, not proof of implementation. Read accessible
project memory and transcripts; label unavailable history UNKNOWN.

## Execution prompt

Continue the existing AURA repository; do not create a replacement project or
discard its architecture. Deliver a premium, responsive, installable owner-facing
trading workstation. Audit current main and PR #56 against every requirement
below. For each feature record its screen, backend path, permissions, real data
source, automated tests, observed runtime result and remaining blocker. Code
presence, a sidebar entry or green CI alone is not completion.

1. Provide clear desktop/mobile navigation and owner access to Command Center,
   scanner, charts, opportunities, trading desk, portfolio, risk, agents, CEO
   decisions, chat/voice, forecasts, news/macro, watchlists, strategy library,
   Algo Studio, backtests, paper/demo, journal, performance, learning, knowledge,
   brokers/data, alerts, health, controlled repair, settings and owner controls.
2. Wire actual backend features to usable controls. Show loading, empty, stale,
   unavailable, permission-denied and failure states. Never fabricate live prices,
   fills, returns, forecasts, learning progress or connected-provider badges.
3. Show searchable broker instruments with exact symbol, description, asset type,
   trading permission and feed freshness. Prioritize gold, Bitcoin and US oil;
   do not substitute similarly named equities/ETFs for spot/CFD instruments.
   Expose unavailable requested instruments and the required broker/feed action.
   Distinguish discovered universe from active scan coverage.
4. Provide real-source candle charts, symbol/timeframe selection, useful indicators,
   positions/orders overlays where supported, and explicit timestamp provenance.
5. Continuously ingest and analyze available market/news data with provenance,
   source trust and point-in-time validation. Forecasts show horizon, uncertainty,
   evaluation evidence and abstention, never guaranteed predictions.
6. Preserve the cognitive pipeline: perceive, contextualize, recall, forecast,
   challenge, CEO synthesis, independent risk, execution and outcome learning.
   Human-inspired reasoning is not a consciousness or AGI claim.
7. Gather versioned strategies in one library with assumptions, entry/exit logic,
   data requirements and evidence. One-click conversion creates a bounded algo
   candidate through the existing DSL/compiler, not automatic live approval.
8. Run causal backtests with costs, holdout/walk-forward and robustness checks.
   Track candidate, validated, paper/demo and human-approved stages separately.
9. Learn from observed trades, missed opportunities and failures with persistent
   provenance. Bounded challenger changes require validation and rollback;
   learning cannot rewrite historical fills or modify risk authority.
10. Verify DEMO account mode before demo execution. Diagnose no-trade reasons
    visibly; never force trades or relax data/risk gates to create activity.
    Real-money release remains subject to existing forward evidence and explicit
    human approval. Broad PC access is not permission to bypass those controls.
11. Preserve secrets, owner authentication, audit logs, idempotency, reconciliation,
    recovery, kill switch and independent RiskEngine. AI cannot change financial
    authority, transfer funds or self-approve deployment.
12. Repair CI/governance artifacts, add regression tests, verify package/static
    assets, inspect the actual UI and validate GitHub Actions on the exact commit.
    Provide operational setup, backup/restore and known-limitations documentation.

Work efficiently using batched independent checks and focused tests before full
validation. Preserve existing user changes. Continue safe in-scope work until
acceptance is demonstrated or an external dependency requires owner action.
Do not promise an overnight deadline or claim unattended future work unless a
supported continuation mechanism is actually configured.

## Release acceptance

Every row of the feature audit must be VERIFIED or explicitly EXTERNALLY BLOCKED
with evidence and an actionable reason. Internal missing implementation is not an
external blocker. Record exact tested commit, local checks, CI runs, UI evidence,
demo order/rejection/reconciliation evidence and recovery checks. Separate software
readiness, demo execution readiness and real-money eligibility. Say "final project
completed" only when the agreed scope is genuinely complete; otherwise give the
remaining items without hiding them behind a passing test count.

## Initial audit findings (not completion claims)

- Existing premium shell and chart path do not prove every owner workflow works.
- Broker symbol coverage and chart discoverability need end-to-end verification.
- Last observed running runtime had no demonstrated broker fills.
- Unverified candle gaps were being silently discarded by the multi-timeframe
  quality gate while consumers retained full history. Restore full-history
  validation before further execution-readiness claims.
- Current release remains paper/demo candidate, not certified real-money service.
