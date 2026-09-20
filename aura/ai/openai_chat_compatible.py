from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aura.ai.openai_responses import OpenAIResponsesError, StructuredResponse

JsonTransport = Callable[
    [str, dict[str, Any], Mapping[str, str], float],
    Awaitable[dict[str, Any]],
]

_GEMINI_CHAT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)
_NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")


class GeminiOpenAIChatClient:
    """Minimal fixed-endpoint OpenAI-compatible chat structured-output client."""

    provider_id = "gemini"
    key_env = "GEMINI_API_KEY"
    chat_url = _GEMINI_CHAT_URL
    strict_json_schema = True

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 90.0,
        transport: JsonTransport | None = None,
        request_limiter: asyncio.Semaphore | None = None,
    ) -> None:
        normalized_model = model_id.strip()
        if _MODEL_ID_PATTERN.fullmatch(normalized_model) is None:
            raise ValueError("invalid Gemini model_id")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        resolved_key = api_key if api_key is not None else os.getenv(self.key_env, "")
        if not resolved_key.strip():
            raise ValueError(f"{self.key_env} is required for the {self.provider_id} provider")
        self.model_id = normalized_model
        self.timeout_seconds = timeout_seconds
        self._api_key = resolved_key.strip()
        self._transport = transport or _default_json_transport
        self._request_limiter = request_limiter

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(model_id={self.model_id!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, api_key=<redacted>)"
        )

    async def structured(
        self,
        *,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> StructuredResponse:
        if not system_prompt.strip():
            raise ValueError("system_prompt is required")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", schema_name):
            raise ValueError("schema_name must be a safe lowercase identifier")
        effective_system_prompt = system_prompt
        response_format: dict[str, Any]
        if self.strict_json_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": dict(schema),
                },
            }
        else:
            response_format = {"type": "json_object"}
            effective_system_prompt = (
                system_prompt
                + "\nReturn only a JSON object matching this schema exactly: "
                + json.dumps(dict(schema), separators=(",", ":"), default=str)
            )
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": effective_system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        dict(user_payload),
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ),
                },
            ],
            "response_format": response_format,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._request_limiter is None:
            response = await self._transport(
                self.chat_url,
                payload,
                headers,
                self.timeout_seconds,
            )
        else:
            async with self._request_limiter:
                response = await self._transport(
                    self.chat_url,
                    payload,
                    headers,
                    self.timeout_seconds,
                )
        output_text = _extract_chat_content(response)
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OpenAIResponsesError(
                f"{self.provider_id} returned invalid structured JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise OpenAIResponsesError(
                f"{self.provider_id} structured output must be a JSON object"
            )
        response_id = response.get("id")
        if not isinstance(response_id, str) or not response_id.strip():
            response_id = f"{self.provider_id}-chat"
        returned_model = response.get("model")
        return StructuredResponse(
            response_id=response_id,
            model_id=returned_model if isinstance(returned_model, str) else self.model_id,
            output=parsed,
        )



class NvidiaOpenAIChatClient(GeminiOpenAIChatClient):
    """NVIDIA NIM hosted chat client using the fixed integrate.api.nvidia.com endpoint."""

    provider_id = "nvidia"
    key_env = "NVIDIA_API_KEY"
    chat_url = _NVIDIA_CHAT_URL
    strict_json_schema = False


def _extract_chat_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices", [])
    if not isinstance(choices, list) or not choices:
        raise OpenAIResponsesError("OpenAI-compatible response has no choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise OpenAIResponsesError("OpenAI-compatible response choice is invalid")
    message = choice.get("message", {})
    if not isinstance(message, dict):
        raise OpenAIResponsesError("OpenAI-compatible response message is invalid")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise OpenAIResponsesError(
            "OpenAI-compatible response has no structured output text"
        )
    return content


async def _default_json_transport(
    url: str,
    payload: dict[str, Any],
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _sync_json_post,
        url,
        payload,
        headers,
        timeout_seconds,
    )


def _sync_json_post(
    url: str,
    payload: dict[str, Any],
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise OpenAIResponsesError(
            f"OpenAI-compatible chat API returned HTTP {exc.code}",
            status_code=exc.code,
        ) from exc
    except URLError as exc:
        raise OpenAIResponsesError("OpenAI-compatible chat API transport failed") from exc
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OpenAIResponsesError("OpenAI-compatible chat API returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise OpenAIResponsesError("OpenAI-compatible chat API returned a non-object payload")
    return decoded
