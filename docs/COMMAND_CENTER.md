# AURA Command Center

AURA includes a deterministic command/privilege boundary plus a local-first mobile/PWA operator surface for a Jarvis-style text or voice interface.

Supported intent classes include:

- market scan;
- system/status;
- risk status;
- positions/portfolio;
- explanation;
- research request;
- paper control;
- live control.

The underlying typed command model remains broker-independent. Read-only commands cannot become orders, research and paper actions have separate privilege levels, and `LIVE_CONTROL` is disabled by default. Even if deployment governance later enables a live handler elsewhere, the command model itself does not bypass AURA's RiskEngine, execution policy, reconciliation, or human live approval.

## Local PWA

Start the command center with:

```bash
python examples/run_command_center.py
```

Then open `http://127.0.0.1:8765`. Supported browsers may expose speech-to-text through the browser Web Speech API; typed commands always remain available. Voice produces text which still passes through the same deterministic command classifier, so speech does not create a second execution path.

The PWA/API surface is deliberately narrower than the core router:

- it has no broker submit/cancel adapter;
- live-money intents are rejected with HTTP 403 before handler execution;
- paper execution-control intents are also rejected by this observation/research surface;
- market, portfolio, and risk values are never invented; until governed sources are attached, the API returns `source_available=false` instead of synthetic values;
- research/change requests are append-only, SHA-256 checksummed, flushed with `fsync`, and revalidated on restart;
- queued research is marked `pending_human_review` and `auto_promotion_allowed=false`;
- optional idempotency keys are persisted only as SHA-256 digests, not raw keys.
- research/change requests require an authenticated owner token even on loopback;
- every queued request records the configured non-secret owner ID, while the token is never persisted.

## Network exposure

The default bind is loopback-only:

```text
AURA_COMMAND_CENTER_HOST=127.0.0.1
AURA_COMMAND_CENTER_PORT=8765
AURA_COMMAND_CENTER_QUEUE=artifacts/operator/research_requests.jsonl
AURA_COMMAND_CENTER_OWNER_ID=owner
AURA_COMMAND_CENTER_TOKEN=
```

Set `AURA_COMMAND_CENTER_TOKEN` to at least 32 random characters before submitting
research or self-upgrade requests. Read-only loopback status remains usable without a
token, but privileged requests fail closed. Binding to a non-loopback address also
fails closed without this token. API callers send it as `Authorization: Bearer ...`.
The PWA keeps a supplied token only in browser `sessionStorage`, which is cleared
when the tab/session ends; it never writes the token into AURA's queue. Never commit it.

## API

- `GET /api/health` — command-center health and safety state.
- `GET /api/status` — operator snapshot used by the PWA.
- `POST /api/command` with JSON `{"text":"system status"}` — deterministic command classification.
- `Idempotency-Key` is optional for read-only commands and recommended for research requests.

Example:

```bash
curl http://127.0.0.1:8765/api/status
curl -X POST http://127.0.0.1:8765/api/command \
  -H "Authorization: Bearer $AURA_COMMAND_CENTER_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: owner-request-001' \
  -d '{"text":"research XAUUSD regime filters"}'
```

A request such as `go live` or `paper start` is rejected by design. Enabling live money requires the separate controlled-live governance process, broker-origin validation, independent risk approval, reconciliation evidence, and explicit human approval. The PWA is not a shortcut around those controls.
