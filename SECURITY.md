# Security Policy for AURA AI OS

AURA handles financial decision infrastructure. Security boundaries are part of correctness.

## Secrets

- Never commit broker/exchange API keys, passwords, tokens, private keys or webhook secrets.
- Secrets must enter through deployment-time secret stores/environment configuration.
- Example configuration must contain placeholders only.
- Prefer least-privilege API credentials. Trading credentials should not have withdrawal permissions where the venue supports separate permissions.
- Rotate a credential immediately if it is exposed in source, logs, screenshots or issue content.

## Live execution boundary

- Strategy and AI modules must not call broker SDKs directly.
- All execution goes through approved broker adapters and the independent risk engine.
- A live runtime must reject strategy versions that are not governance-approved.
- AI/research automation cannot perform final live approval or mutate deployed strategy code.
- Kill switches and flattening paths must not depend on an LLM being available.

## Logging and audit

Do not log:
- API secrets or authorization headers
- passwords or private keys
- full sensitive account payloads when a redacted representation is sufficient

Do log structured identifiers needed for audit/reconciliation:
- strategy/version hash
- decision/risk reason
- client order ID and broker order ID
- fill ID
- correlation/event ID
- connector health transitions

## Dependency and supply-chain policy

- Minimize runtime dependencies.
- Review new dependencies before adding them to the execution path.
- Pin or constrain versions intentionally and keep CI active across supported Python versions.
- Production images/environments should be reproducible and immutable.

## Reporting a vulnerability

Do not publish credentials or exploitable account details in a public issue. Revoke/rotate any affected secret first, then report the defect through a private channel available to the repository owner.

## Current deployment status

The repository is currently an engineering/research foundation. Live-money execution is intentionally not enabled by the present codebase.
