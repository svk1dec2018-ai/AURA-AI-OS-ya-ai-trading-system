from pathlib import Path

from aura.agents.ai_council import build_env_ai_council_from_env
from aura.agents.local_gateway_provider import build_gateway_providers_from_env
from aura.ops import final_doctor
from aura.prime.ai_readiness import ai_provider_matrix


def test_local_gateway_is_in_the_advisory_council_without_paid_key(monkeypatch) -> None:
    monkeypatch.setenv("AURA_FREE_AI_PRESET", "off")
    monkeypatch.setenv("AURA_OLLAMA_MODELS", "")
    for name in ("OPENAI_API_KEY", "NVIDIA_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AURA_COMPAT_BASE_URL", "http://127.0.0.1:20128/v1")
    monkeypatch.setenv("AURA_COMPAT_MODEL", "auto/best-coding")
    monkeypatch.delenv("AURA_COMPAT_API_KEY", raising=False)
    providers = build_gateway_providers_from_env()
    assert len(providers) == 1
    assert providers[0].provider_id == "compatible"
    council = build_env_ai_council_from_env()
    assert council
    assert all(agent.provider.provider_id == "compatible" for agent in council)


def test_cloud_readiness_never_exposes_keys_or_claims_a_connection(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "private-test-key")
    monkeypatch.setenv("AURA_GROQ_MODELS", "openai/gpt-oss-20b")
    rows = ai_provider_matrix()
    assert "private-test-key" not in repr(rows)
    groq = next(row for row in rows if row["provider_id"] == "groq")
    assert groq["configured"] is True
    assert groq["execution_authority"] is False
    assert "Connection verified" not in repr(groq)


def test_key_free_dashboard_doctor_does_not_grant_demo_readiness(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(final_doctor, "_http_ok", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(final_doctor, "_module_present", lambda _name: False)
    monkeypatch.delenv("AURA_LIVE_TRADING_ENABLED", raising=False)
    for name in ("AURA_MT5_DEMO_LOGIN", "AURA_MT5_DEMO_PASSWORD", "AURA_MT5_DEMO_SERVER"):
        monkeypatch.delenv(name, raising=False)
    assert final_doctor.build_report(root, profile="prime-ui").ready is True
    demo = final_doctor.build_report(root, profile="prime-local")
    assert demo.ready is False
    assert demo.live_money_eligible is False
    assert any(row.check_id == "mt5-demo-config" and not row.passed for row in demo.checks)
