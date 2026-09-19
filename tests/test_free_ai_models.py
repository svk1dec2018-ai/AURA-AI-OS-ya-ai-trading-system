from __future__ import annotations

import json

import pytest

from aura.ai.free_ai_cli import main, probe_local_models
from aura.ai.free_models import (
    BALANCED_FIVE,
    configured_ollama_model_ids,
    free_ai_catalog_payload,
    get_free_ai_preset,
    parse_ollama_keep_alive,
)

EXPECTED_BALANCED_FIVE = (
    "qwen3.5:4b",
    "deepseek-r1:8b",
    "llama3.1:8b",
    "gemma3:4b",
    "phi4-mini:3.8b",
)


def test_balanced_five_is_curated_key_free_and_not_a_quality_claim() -> None:
    assert tuple(profile.model_id for profile in BALANCED_FIVE) == EXPECTED_BALANCED_FIVE
    assert get_free_ai_preset("free5") == BALANCED_FIVE
    payload = free_ai_catalog_payload()
    assert payload["model_count"] == 5
    assert payload["approximate_total_download_gb"] == pytest.approx(19.3)
    assert payload["api_key_required"] is False
    assert payload["per_token_charge"] is False
    assert payload["performance_equivalence_claimed"] is False
    assert payload["fund_operations_available"] is False
    assert payload["risk_bypass_available"] is False


def test_explicit_models_override_preset_and_preserve_unique_order() -> None:
    environment = {
        "AURA_FREE_AI_PRESET": "balanced5",
        "AURA_OLLAMA_MODELS": "custom-a,custom-b,custom-a",
    }
    assert configured_ollama_model_ids(environment) == ("custom-a", "custom-b")
    assert configured_ollama_model_ids({"AURA_FREE_AI_PRESET": "balanced5"}) == (
        EXPECTED_BALANCED_FIVE
    )
    assert configured_ollama_model_ids({"AURA_FREE_AI_PRESET": "off"}) == ()


def test_unknown_preset_and_unbounded_keep_alive_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown free AI preset"):
        get_free_ai_preset("mystery")
    with pytest.raises(ValueError, match="forever"):
        parse_ollama_keep_alive(-1)
    with pytest.raises(ValueError, match="positive duration"):
        parse_ollama_keep_alive("forever")
    with pytest.raises(ValueError, match="24h"):
        parse_ollama_keep_alive("25h")
    with pytest.raises(TypeError, match="string or integer"):
        parse_ollama_keep_alive(1.5)  # type: ignore[arg-type]
    assert parse_ollama_keep_alive("0") == 0
    assert parse_ollama_keep_alive("30s") == "30s"


def test_probe_reports_exact_missing_models_without_credentials() -> None:
    def tags_loader(url: str, timeout_seconds: float) -> dict:
        assert url == "http://127.0.0.1:11434/api/tags"
        assert timeout_seconds == 2.0
        return {
            "models": [
                {"name": "qwen3.5:4b"},
                {"model": "deepseek-r1:8b"},
            ]
        }

    payload = probe_local_models(timeout_seconds=2.0, tags_loader=tags_loader)
    assert payload["ready"] is False
    assert payload["installed_required_models"] == EXPECTED_BALANCED_FIVE[:2]
    assert payload["missing_models"] == EXPECTED_BALANCED_FIVE[2:]
    assert payload["credentials_used"] is False
    assert payload["cloud_models_used"] is False
    assert payload["fund_operations_available"] is False


def test_catalog_cli_emits_machine_readable_safety_metadata(capsys) -> None:
    assert main(["catalog"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["model_id"] for item in payload["models"]] == list(
        EXPECTED_BALANCED_FIVE
    )
    assert payload["advisory_or_owner_gated_only"] is True


def test_probe_rejects_non_local_ollama_endpoint() -> None:
    with pytest.raises(ValueError, match="local HTTP endpoint"):
        probe_local_models(base_url="https://example.com")
