from __future__ import annotations

import os

from aura.agents.openai_provider import OpenAIReasoningProvider
from aura.ai.openai_compatible import OpenAICompatibleStructuredClient


class LocalGatewayReasoningProvider(OpenAIReasoningProvider):
    """Advisory gateway provider using the same local/cloud route as maintenance."""

    provider_id = "compatible"


def build_gateway_providers_from_env() -> tuple[LocalGatewayReasoningProvider, ...]:
    base_url = os.getenv("AURA_COMPAT_BASE_URL", "").strip()
    model = os.getenv("AURA_COMPAT_MODEL", "").strip()
    if not base_url or not model:
        return ()
    client = OpenAICompatibleStructuredClient(
        model,
        base_url=base_url,
        api_key=os.getenv("AURA_COMPAT_API_KEY", ""),
        timeout_seconds=float(os.getenv("AURA_COMPAT_TIMEOUT_SECONDS", "120")),
    )
    return (LocalGatewayReasoningProvider(model, client=client),)
