# AURA AI OS vision coverage audit

This is a code-evidence map, not a marketing checklist. `IMPLEMENTED` means a
concrete module and tests exist. `PARTIAL` means the safety/core contract exists
but a production integration or client-facing surface is still missing.
`EXTERNAL GATE` means completion requires credentials, elapsed forward operation
or human approval and cannot be manufactured in source code.

| Vision capability | Status | Code evidence | Remaining boundary |
|---|---|---|---|
| Multi-market, multi-timeframe scanning | IMPLEMENTED | `aura/runtime/scanner.py`, `aura/runtime/multi_market_paper.py`, `aura/markets/universe.py` | Coverage depends on connected data feeds and entitlements. |
| Ten specialist intelligence roles | IMPLEMENTED | `aura/agents/models.py`, `aura/agents/specialists.py`, `aura/agents/external_specialists.py` | Provider-specific evidence can abstain when trustworthy data is unavailable. |
| Multi-model local AI council | IMPLEMENTED | `aura/agents/ai_council.py`, `aura/agents/ollama_provider.py`, `aura/agents/adaptive_model_router.py` | Ollama and user-selected local models must be installed on the host. |
| Deep/adversarial reasoning | IMPLEMENTED | `aura/agents/deliberation.py` | Raw private model reasoning is not treated as financial evidence. |
| CEO decision layer | IMPLEMENTED | `aura/agents/orchestrator.py`, `aura/agents/service.py` | CEO has no authority to bypass independent risk controls. |
| Deterministic evidence schema and explainability | IMPLEMENTED | `aura/agents/models.py`, `aura/agents/audit.py` | UI presentation remains partial. |
| Independent financial Risk Engine and kill switch | IMPLEMENTED | `aura/risk/engine.py`, `aura/core/pipeline.py` | Broker/venue limits require account-specific validation. |
| Portfolio and order source of truth | IMPLEMENTED | `aura/portfolio/ledger.py`, `aura/execution/state.py`, `aura/persistence/wal.py` | Live broker reconciliation is an external gate. |
| Paper execution and restart recovery | IMPLEMENTED | `aura/execution/paper.py`, `aura/persistence/recovery.py`, `aura/runtime/autonomous_paper.py` | Sustained forward paper evidence must accrue over real time. |
| Knowledge/RAG firewall | IMPLEMENTED | `aura/knowledge/firewall.py`, `aura/knowledge/local_corpus.py` | Only authorized/public content may be ingested. |
| Live news and macro context | IMPLEMENTED | `aura/data/free_intelligence.py`, `aura/data/intelligence_service.py` | Optional FRED/Alpha Vantage sources require user-owned keys. |
| Historical research provenance | IMPLEMENTED | `aura/research/manifest.py`, `aura/data/public_history.py` | Licensed datasets must be supplied by the operator where required. |
| Strategy invention and bounded evolution | IMPLEMENTED | `aura/research/autonomous_strategy_lab.py`, `aura/research/strategy_factory.py`, `aura/research/strategy_mutation.py` | Research output cannot auto-deploy live. |
| Backtest, purged walk-forward and Monte Carlo | IMPLEMENTED | `aura/backtest/`, `aura/research/robustness.py` | Realistic market-specific costs require current broker/venue inputs. |
| Sealed holdout, stability and regime tests | IMPLEMENTED | `aura/research/holdout.py`, `aura/research/parameter_stability.py`, `aura/research/regime_validation.py` | Strategy-specific evidence must still be produced. |
| Point-in-time equities/futures/options research | IMPLEMENTED | `aura/data/corporate_actions.py`, `aura/data/futures_roll.py`, `aura/data/options_replay.py` | Reliable licensed option-chain history remains dataset-dependent. |
| Self-learning from trades and missed opportunities | IMPLEMENTED | `aura/evolution/online_learning.py`, `aura/evolution/opportunity_audit.py`, `aura/evolution/shadow_outcomes.py` | Learning remains advisory/research until governed validation passes. |
| Strategy versioning and approval lifecycle | IMPLEMENTED | `aura/research/lifecycle.py` | Final approval requires a human actor. |
| Local voice announcements | IMPLEMENTED | `aura/interface/voice_alerts.py`, `examples/run_free_public_autonomy.py` | Full speech-to-text conversation is not implemented. |
| Jarvis-style command privilege boundary | IMPLEMENTED | `aura/interface/command_center.py` | A graphical/chat frontend and production handlers remain partial. |
| Dashboard/command-center UI | PARTIAL | Typed command model and runtime JSON status exist. | Full graphical real-time UI is not included. |
| Telegram/WhatsApp delivery | PENDING | Alert contracts/voice exist. | Provider adapter, user destination and delivery receipts are required. |
| Dhan Indian-market paper runtime | IMPLEMENTED, UNVALIDATED ACCOUNT | `aura/runtime/dhan_learning_daemon.py`, Dhan data modules | Requires user-owned Dhan credentials and subscription validation. |
| MT5 forex/metals demo runtime | IMPLEMENTED, UNVALIDATED ACCOUNT | `aura/runtime/mt5_learning_daemon.py`, `aura/execution/mt5_demo_broker.py` | Requires Windows MT5 DEMO credentials and terminal validation. |
| Angel One adapter | IMPLEMENTED, READ-ONLY/UNVALIDATED ACCOUNT | `aura/execution/angel_one.py`, `examples/check_angel_one_account.py` | Profile, quote, order/trade book, positions, routing and reconciliation are implemented. Submit/cancel stay locked pending static-IP and broker-origin validation. |
| Unrestricted live-money readiness | EXTERNAL GATE | `aura/ops/release_gate.py`, `aura/ops/preflight.py` | Sequential phases, broker-origin evidence and explicit human approval are mandatory. |

## Truthful conclusion

The core AURA vision - governed multi-agent intelligence, a deterministic CEO,
knowledge grounding, research/evolution, paper execution, learning, auditability
and risk-first authority - is present. The largest remaining product gaps are a
full graphical/conversational frontend, external alert delivery, controlled Angel One
execution validation, and credential-backed long-duration broker validation. Those gaps do not justify
removing the existing safety gates or claiming guaranteed trading accuracy.
