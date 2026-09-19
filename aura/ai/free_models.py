from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class FreeModelProfile:
    """Curated local model metadata; it grants no AURA authority."""

    model_id: str
    family: str
    primary_role: str
    approximate_download_gb: float
    source_url: str
    license_note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


BALANCED_FIVE: tuple[FreeModelProfile, ...] = (
    FreeModelProfile(
        model_id="qwen3.5:4b",
        family="Qwen 3.5",
        primary_role="general reasoning and code review",
        approximate_download_gb=3.4,
        source_url="https://ollama.com/library/qwen3.5",
        license_note="Review the model card and bundled license before use.",
    ),
    FreeModelProfile(
        model_id="deepseek-r1:8b",
        family="DeepSeek-R1 Distill",
        primary_role="deliberate reasoning and counter-analysis",
        approximate_download_gb=5.2,
        source_url="https://ollama.com/library/deepseek-r1",
        license_note="Review the model card and upstream model license before use.",
    ),
    FreeModelProfile(
        model_id="llama3.1:8b",
        family="Llama 3.1",
        primary_role="broad instruction following and synthesis",
        approximate_download_gb=4.9,
        source_url="https://ollama.com/library/llama3.1",
        license_note="Use is subject to the Llama 3.1 Community License.",
    ),
    FreeModelProfile(
        model_id="gemma3:4b",
        family="Gemma 3",
        primary_role="compact multilingual analysis",
        approximate_download_gb=3.3,
        source_url="https://ollama.com/library/gemma3",
        license_note="Use is subject to Google's Gemma terms.",
    ),
    FreeModelProfile(
        model_id="phi4-mini:3.8b",
        family="Phi-4 Mini",
        primary_role="compact reasoning and numerical cross-checks",
        approximate_download_gb=2.5,
        source_url="https://ollama.com/library/phi4-mini",
        license_note="Review the model card and bundled license before use.",
    ),
)

FREE_AI_PRESETS: Mapping[str, tuple[FreeModelProfile, ...]] = {
    "balanced5": BALANCED_FIVE,
}

_PRESET_ALIASES = {
    "balanced": "balanced5",
    "default": "balanced5",
    "free5": "balanced5",
}
_DISABLED_PRESETS = {"", "0", "false", "none", "off"}
_KEEP_ALIVE_PATTERN = re.compile(r"^(?:0|[1-9]\d*(?:\.\d+)?(?:ms|s|m|h)?)$")
_MAX_KEEP_ALIVE_SECONDS = 24 * 60 * 60


def get_free_ai_preset(name: str) -> tuple[FreeModelProfile, ...]:
    normalized = name.strip().lower()
    if normalized in _DISABLED_PRESETS:
        return ()
    normalized = _PRESET_ALIASES.get(normalized, normalized)
    try:
        return FREE_AI_PRESETS[normalized]
    except KeyError as exc:
        valid = ", ".join(sorted(FREE_AI_PRESETS))
        raise ValueError(f"unknown free AI preset {name!r}; valid presets: {valid}, off") from exc


def configured_ollama_model_ids(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Resolve an explicit model list or the selected curated local preset.

    `AURA_OLLAMA_MODELS` wins when non-empty. A preset never downloads or starts
    a model by itself; it only supplies model identifiers to existing AURA paths.
    """

    env = os.environ if environment is None else environment
    explicit = env.get("AURA_OLLAMA_MODELS", "")
    models = _unique_models(explicit)
    if models:
        return models
    preset = get_free_ai_preset(env.get("AURA_FREE_AI_PRESET", ""))
    return tuple(profile.model_id for profile in preset)


def parse_ollama_keep_alive(value: str | int) -> str | int:
    """Accept a bounded Ollama duration and reject keep-forever values."""

    if isinstance(value, bool):
        raise TypeError("Ollama keep_alive must be 0 or a positive duration")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("Ollama keep_alive cannot keep a model loaded forever")
        if value > _MAX_KEEP_ALIVE_SECONDS:
            raise ValueError("Ollama keep_alive cannot exceed 24h")
        return value
    if not isinstance(value, str):
        raise TypeError("Ollama keep_alive must be a string or integer")
    normalized = value.strip().lower()
    if _KEEP_ALIVE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(
            "Ollama keep_alive must be 0 or a positive duration such as 30s or 5m"
        )
    if normalized.isdigit():
        return parse_ollama_keep_alive(int(normalized))
    amount = float(normalized[:-2] if normalized.endswith("ms") else normalized[:-1])
    multiplier = (
        0.001
        if normalized.endswith("ms")
        else 60
        if normalized.endswith("m")
        else 3600
        if normalized.endswith("h")
        else 1
    )
    if amount * multiplier > _MAX_KEEP_ALIVE_SECONDS:
        raise ValueError("Ollama keep_alive cannot exceed 24h")
    return normalized


def free_ai_catalog_payload(preset_name: str = "balanced5") -> dict[str, Any]:
    profiles = get_free_ai_preset(preset_name)
    return {
        "preset": preset_name,
        "models": [profile.as_dict() for profile in profiles],
        "model_count": len(profiles),
        "approximate_total_download_gb": round(
            sum(profile.approximate_download_gb for profile in profiles),
            1,
        ),
        "local_inference": True,
        "api_key_required": False,
        "per_token_charge": False,
        "performance_equivalence_claimed": False,
        "advisory_or_owner_gated_only": True,
        "fund_operations_available": False,
        "risk_bypass_available": False,
    }


def _unique_models(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
