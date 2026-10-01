from __future__ import annotations

import os
from urllib.parse import urlsplit


def ai_provider_matrix() -> tuple[dict[str, object], ...]:
    ollama_models = os.getenv("AURA_OLLAMA_MODELS", "").strip()
    preset = os.getenv("AURA_FREE_AI_PRESET", "off").strip().lower()
    ollama_configured = bool(ollama_models) or preset not in {"", "off", "none"}

    compat_url = os.getenv("AURA_COMPAT_BASE_URL", "").strip()
    compat_model = os.getenv("AURA_COMPAT_MODEL", "").strip()
    compat_key = os.getenv("AURA_COMPAT_API_KEY", "").strip()
    compat_host = _safe_host(compat_url)
    compat_local = compat_host in {
        "127.0.0.1",
        "::1",
        "localhost",
        "host.docker.internal",
    }
    compat_missing: list[str] = []
    if not compat_url:
        compat_missing.append("AURA_COMPAT_BASE_URL")
    if not compat_model:
        compat_missing.append("AURA_COMPAT_MODEL")
    if compat_url and not compat_local and not compat_key:
        compat_missing.append("AURA_COMPAT_API_KEY")

    openai_configured = bool(os.getenv("OPENAI_API_KEY", "").strip())

    return (
        {
            "provider_id": "ollama",
            "display_name": "Ollama Local",
            "configured": ollama_configured,
            "free_first": True,
            "local": True,
            "missing_env": (
                []
                if ollama_configured
                else ["AURA_FREE_AI_PRESET or AURA_OLLAMA_MODELS"]
            ),
            "execution_authority": False,
            "notes": ["Preferred key-free local AI route."],
        },
        {
            "provider_id": "compatible",
            "display_name": "OmniRoute / OpenRouter Compatible",
            "configured": not compat_missing,
            "free_first": compat_local or bool(compat_url),
            "local": compat_local,
            "host": compat_host,
            "missing_env": compat_missing,
            "execution_authority": False,
            "notes": [
                "Local OmniRoute can be key-free from AURA's perspective.",
                "Cloud compatible endpoints require an environment API key.",
            ],
        },
        {
            "provider_id": "openai",
            "display_name": "OpenAI Optional",
            "configured": openai_configured,
            "free_first": False,
            "local": False,
            "missing_env": [] if openai_configured else ["OPENAI_API_KEY"],
            "execution_authority": False,
            "notes": ["Optional; AURA Prime does not require paid OpenAI."],
        },
    )


def _safe_host(url: str) -> str:
    if not url:
        return ""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
