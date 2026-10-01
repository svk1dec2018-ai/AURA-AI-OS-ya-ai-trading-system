from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CredentialGroup:
    group_id: str
    display_name: str
    purpose: str
    required_now: bool
    alternatives: tuple[tuple[str, ...], ...]
    notes: tuple[str, ...] = ()

    def configured(self) -> bool:
        return any(
            all(bool(os.environ.get(name, "").strip()) for name in alternative)
            for alternative in self.alternatives
        )

    def missing_alternatives(self) -> tuple[tuple[str, ...], ...]:
        if self.configured():
            return ()
        return tuple(
            tuple(name for name in alternative if not os.environ.get(name, "").strip())
            for alternative in self.alternatives
        )


PRIME_CREDENTIAL_GROUPS: tuple[CredentialGroup, ...] = (
    CredentialGroup(
        group_id="mt5_demo",
        display_name="MT5 DEMO",
        purpose="Forex, metals, energy, global indices and broker CFD demo execution",
        required_now=True,
        alternatives=(
            (
                "AURA_MT5_DEMO_LOGIN",
                "AURA_MT5_DEMO_PASSWORD",
                "AURA_MT5_DEMO_SERVER",
            ),
        ),
        notes=("API key is not required; use DEMO account credentials.",),
    ),
    CredentialGroup(
        group_id="india_market_data",
        display_name="India market feed",
        purpose="NSE/BSE/NFO/BFO/MCX account-bound real-time data",
        required_now=False,
        alternatives=(
            ("AURA_DHAN_CLIENT_ID", "AURA_DHAN_ACCESS_TOKEN"),
            (
                "AURA_ANGEL_ONE_API_KEY",
                "AURA_ANGEL_ONE_CLIENT_CODE",
                "AURA_ANGEL_ONE_JWT_TOKEN",
                "AURA_ANGEL_ONE_REFRESH_TOKEN",
            ),
            (
                "AURA_SHOONYA_USER_ID",
                "AURA_SHOONYA_ACCOUNT_ID",
                "AURA_SHOONYA_SESSION_TOKEN",
            ),
            (
                "AURA_FLATTRADE_USER_ID",
                "AURA_FLATTRADE_ACCOUNT_ID",
                "AURA_FLATTRADE_ACCESS_TOKEN",
            ),
        ),
        notes=("Only one supported India broker feed is needed to start.",),
    ),
    CredentialGroup(
        group_id="local_ai",
        display_name="Local/free AI",
        purpose="Maintenance, research and advisory reasoning",
        required_now=False,
        alternatives=(
            ("AURA_OLLAMA_MODELS",),
            ("AURA_COMPAT_BASE_URL", "AURA_COMPAT_MODEL"),
        ),
        notes=(
            "Local Ollama or local OmniRoute can satisfy this without a paid API key.",
            "AI never receives broker execution authority.",
        ),
    ),
    CredentialGroup(
        group_id="alerts",
        display_name="Telegram alerts",
        purpose="Optional outbound notifications",
        required_now=False,
        alternatives=(("AURA_TELEGRAM_BOT_TOKEN", "AURA_TELEGRAM_CHAT_ID"),),
    ),
)


def credential_plan() -> tuple[dict[str, object], ...]:
    rows = []
    for group in PRIME_CREDENTIAL_GROUPS:
        rows.append(
            {
                "group_id": group.group_id,
                "display_name": group.display_name,
                "purpose": group.purpose,
                "required_now": group.required_now,
                "configured": group.configured(),
                "missing_alternatives": [
                    list(alternative) for alternative in group.missing_alternatives()
                ],
                "notes": list(group.notes),
            }
        )
    return tuple(rows)
