from __future__ import annotations

import hmac
import os

OWNER_TOKEN_ENV = "AURA_OWNER_TOKEN"


def configured_owner_token() -> str | None:
    value = os.environ.get(OWNER_TOKEN_ENV, "").strip()
    return value or None


def owner_auth_required() -> bool:
    return configured_owner_token() is not None


def bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    scheme, separator, value = authorization_header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    token = value.strip()
    return token or None


def owner_authorized(authorization_header: str | None) -> bool:
    expected = configured_owner_token()
    if expected is None:
        # The first release is loopback-only. Operators may opt into a token
        # without being forced to manage another secret on a single-user PC.
        return True
    supplied = bearer_token(authorization_header)
    return supplied is not None and hmac.compare_digest(supplied, expected)
