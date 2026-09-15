# AURA Phase-2 Decision Lineage & Replay Evidence — 2026-09-15

## Classification

**Status: REAL software evidence / PARTIAL Phase-2 completion**

This evidence proves deterministic decision fingerprinting and replay mismatch detection for the implemented paths. It does **not** prove broker execution quality, profitability, or complete raw-event-to-order reproducibility across every connector.

## What changed

AURA now has `decision-lineage-v1`, a cryptographic decision fingerprint covering the point-in-time intelligence state used for one decision.

The lineage includes hashes for:

- complete closed-candle decision series;
- decision metadata;
- specialist evidence;
- specialist failures;
- data-quality result;
- bull/bear/counterfactual deliberation;
- CEO decision memo;
- agent evidence-policy decision;
- source IDs and latest source observation time;
- an aggregate lineage hash.

The lineage boundary rejects specialist sources observed after the decision time.

## Runtime wiring

Lineage is generated in:

- `MultiMarketIntelligenceScanner` for healthy decisions and data-quality-blocked decisions;
- `MultiAgentDecisionService` for healthy, blocked, abstained and governed decision paths.

The service path was also corrected to pass the full `AgentContext` into CEO synthesis so contextual reliability weighting is consistent with scanner execution.

## Durable audit evidence

`AgentAuditJournal` now persists:

- round evidence;
- CEO memo;
- deliberation;
- data-quality result;
- agent evidence-policy result;
- decision lineage.

A supplied lineage must verify against the exact decision payload before it can be appended to the checksum-protected WAL.

`MultiMarketPaperCoordinator` passes the scanner lineage into the audit journal, making the fingerprint durable across restart/recovery workflows.

## Replay verification

`DecisionLineageReplayVerifier`:

1. requires an `agent.round.completed` WAL event;
2. requires a valid stored lineage payload;
3. verifies the stored aggregate lineage hash;
4. verifies correlation IDs;
5. verifies the regenerated lineage hash;
6. fails explicitly when stored and regenerated lineage hashes differ.

Replay mismatch is never treated as success.

## Explicit decision clock

The paper coordinator no longer owns an unavoidable hidden wall-clock dependency.

It now accepts an explicit `decision_time_provider`:

- `live_decision_time` captures live processing time while never preceding candle close;
- `event_time_decision` uses the captured event/candle close time for deterministic replay.

CEO memos generated with an `AgentContext` now use `context.created_at` as their decision timestamp. This removed a hidden wall-clock source that initially caused otherwise identical replay lineages to differ.

## Evidence from validation

Final validation artifact: `phase2_replay_determinism_validation.txt`

Validated on Python 3.11 and 3.12:

- editable install: PASS;
- Ruff: PASS;
- complete pytest suite: PASS;
- replay-stable lineage test: PASS.

The replay test independently runs the same paper decision twice using the deterministic event-time clock and requires identical decision lineage hashes in both the in-memory candidate and persisted audit WAL.

## Important failures found during implementation

The work exposed two useful issues rather than hiding them:

1. An older intelligence-service test depended on a fixed August 2026 wall-clock date and became stale. The test was made clock-stable while preserving its original point-in-time filtering assertion.
2. Initial replay lineage still differed after adding the replay clock because CEO memo `generated_at` used an implicit wall clock. CEO decision timestamps were changed to the explicit decision context time.

These failures are evidence that the lineage gate is finding real nondeterminism rather than merely generating hashes.

## What this does NOT yet prove

Phase 2 is not finished. Remaining high-value work includes:

- uniform raw source/event IDs from every live connector through normalized observations and derived bars;
- raw-event -> normalized tick -> candle -> feature -> agent evidence lineage, not only the decision boundary;
- strict canonical metadata serialization that rejects unsupported/non-deterministic object representations instead of falling back to `str(value)`;
- captured live decision timestamps replayed from durable input records for every runtime, not only explicit event-time replay mode;
- deterministic replay checksum across a complete ordered event stream;
- dataset/raw-feed version identity for live replay packages;
- gap/anomaly/reconnect sequence evidence in the replay dossier;
- complete Phase-2 evidence dossier across at least one long-running live public feed and later one broker-origin feed.

## Safety boundary

Decision lineage is an integrity and reproducibility mechanism. It does not grant trading authority.

The authority chain remains:

`data -> specialists/AI -> CEO -> AgentRiskPolicy -> independent RiskEngine -> execution adapter`

No lineage match, model confidence, research result or replay result can bypass the independent RiskEngine, live approval gates or broker-forward evidence requirements.

## Next engineering target

**Strict raw-to-decision provenance.**

Implement stable raw observation IDs and deterministic canonical serialization through the ingestion/aggregation path, then construct an ordered event-stream replay checksum so AURA can prove not only that the final decision fingerprint matches, but exactly which raw observations produced each bar and decision.
