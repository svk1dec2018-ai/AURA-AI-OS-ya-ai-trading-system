# AURA AI OS — AI CONTINUATION INSTRUCTIONS

This repository is a long-running AURA AI OS project. **Do not start the design from scratch.**

## FIRST READ

Before making any material change, read these files in this order:

1. `docs/AURA_PROJECT_MEMORY_A_TO_Z.md` — project memory, history reconstruction, north star, decisions and handoff rules.
2. `README.md` — current product/runtime overview.
3. `docs/IMPLEMENTATION_STATUS.md` — current code-level implementation truth.
4. `docs/PRODUCTION_READINESS.md` — deployment and live-release boundaries.

Then inspect the actual source and tests relevant to the requested change.

## SOURCE-OF-TRUTH HIERARCHY

For **what code actually does**:
`source code + tests + runtime evidence > status docs > README > old documents > AI assumptions`.

For **what AURA is intended to become**:
`AURA Constitution / Project Memory > temporary suggestions`.

For **exact historical code changes**:
`git history / commits / diffs` are authoritative.

## NON-NEGOTIABLE AURA RULES

- AURA is a governed trading intelligence OS, not a chat-controlled buy/sell bot.
- Independent `RiskEngine` has veto authority.
- No LLM may directly set live position quantity, leverage, risk limits, kill switch, broker permissions or unrestricted executable code.
- Strategies evolve through bounded specifications/DSL, validation, paper/demo evidence, approval and rollback.
- Never represent historical, synthetic, public-shadow or backtest evidence as broker-forward live evidence.
- Never remove safety gates merely to make a demo pass.
- Never commit passwords, tokens, API keys, TOTP seeds or live approval credentials.
- Treat data leakage, overfitting, survivorship bias and unrealistic execution as first-class risks.
- Preserve deterministic accounting, order-state semantics, reconciliation and auditability.
- Slow/failed AI must not stall market ingestion.

## CHANGE WORKFLOW

Before changing code:

```text
Read memory -> inspect current source -> inspect tests -> inspect recent git history
-> define exact change -> implement smallest safe change -> add/update tests
-> run relevant verification -> update memory if project intent/state changed -> commit
```

When a change affects architecture, safety, strategy logic, data contracts, validation rules, production gates, or project direction, record it in `docs/AURA_PROJECT_MEMORY_A_TO_Z.md` using the documented change-log format.

## CURRENT NORTH STAR

Build AURA toward a continuously observing, multi-market, broker-agnostic, evidence-driven trading research/execution OS with:

- point-in-time data and deterministic replay;
- specialist deterministic intelligence plus optional multi-model AI;
- Bull/Bear/Counterfactual deliberation;
- reliability-weighted CEO synthesis;
- calibrated abstention;
- independent risk authority;
- realistic execution and reconciliation;
- cognitive memory including negative memory;
- bounded strategy discovery and self-evolution;
- paper/demo-first promotion;
- human-governed tiny live canaries only after measured broker-forward evidence.

## CURRENT RELEASE BOUNDARY

AURA is a production-deployable **paper/demo research service candidate**. It is not yet certified for unrestricted real-money production.

The current default live-canary gate requires broker-origin forward evidence, including at least 1,000 forward trades over 30+ elapsed days, positive expectancy, PF >= 1.10, max drawdown <= 10%, zero critical incidents, zero reconciliation failures, zero unresolved data-integrity incidents, immutable strategy approval, and explicit human live-risk acknowledgement. These are engineering gates, not a profitability guarantee.

## CURRENT PRIORITY

The formal roadmap currently emphasizes **Phase 2: trustworthy point-in-time data, deterministic replay, data quality and lineage**. Do not add cosmetic AI complexity while this evidence is weak.

## HANDOFF PRINCIPLE

When asked to “continue AURA,” first determine:

> What is the current repository truth? What changed since the last known state? What is actually proven? What remains unproven? What is the smallest safe next change that moves the system toward the north star?

Never fabricate missing history. When exact historical ChatGPT conversation text is unavailable, label the reconstruction `RECONSTRUCTED` or `UNKNOWN` instead of inventing details.
