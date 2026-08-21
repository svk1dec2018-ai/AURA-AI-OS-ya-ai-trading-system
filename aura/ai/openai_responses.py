from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

JsonTransport = Callable[
    [str, dict[str, Any], Mapping[str, str], float],
    Awaitable[dict[str, Any]],
]

_OFFICIAL_RESPONSES_URL = "https://api.openai.com/v1/responses"
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


class OpenAIResponsesError(RuntimeError):
    """Safe OpenAI Responses API failure without credential-bearing details."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_type = error_type


class StructuredResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    response_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    output: dict[str, Any]


class OpenAIResponsesClient:
    """Minimal async Responses API client for strict structured output.

    Credentials are accepted only through the process environment (or an explicit
    constructor argument supplied by the host). The endpoint is intentionally fixed
    to OpenAI's HTTPS API so an environment change cannot exfiltrate the key to an
    arbitrary host. AURA never persists the key, request Authorization header, raw
    hidden reasoning, or provider response body.
    """

    provider_id = "openai"

    def __init__(
        self,
        model_id: str = "gpt-5.4-mini",
        *,
        api_key: str | None = None,
        timeout_seconds: float = 90.0,
        transport: JsonTransport | None = None,
        request_limiter: asyncio.Semaphore | None = None,
    ) -> None:
        normalized_model = model_id.strip()
        if _MODEL_ID_PATTERN.fullmatch(normalized_model) is None:
            raise ValueError("invalid OpenAI model_id")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        resolved_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        if not resolved_key.strip():
            raise ValueError("OPENAI_API_KEY is required for the OpenAI provider")
        self.model_id = normalized_model
        self.timeout_seconds = timeout_seconds
        self._api_key = resolved_key.strip()
        self._transport = transport or _default_json_transport
        self._request_limiter = request_limiter

    def __repr__(self) -> str:
        return (
            f"OpenAIResponsesClient(model_id={self.model_id!r}, "
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
        payload = {
            "model": self.model_id,
            "input": [
                {"role": "system", "content": system_prompt},
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
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": dict(schema),
                }
            },
            "store": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._request_limiter is None:
            response = await self._transport(
                _OFFICIAL_RESPONSES_URL,
                payload,
                headers,
                self.timeout_seconds,
            )
        else:
            async with self._request_limiter:
                response = await self._transport(
                    _OFFICIAL_RESPONSES_URL,
                    payload,
                    headers,
                    self.timeout_seconds,
                )
        output_text = _extract_output_text(response)
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OpenAIResponsesError("OpenAI returned invalid structured JSON") from exc
        if not isinstance(parsed, dict):
            raise OpenAIResponsesError("OpenAI structured output must be a JSON object")
        response_id = response.get("id")
        if not isinstance(response_id, str) or not response_id.strip():
            raise OpenAIResponsesError("OpenAI response is missing its audit identifier")
        returned_model = response.get("model")
        return StructuredResponse(
            response_id=response_id,
            model_id=returned_model if isinstance(returned_model, str) else self.model_id,
            output=parsed,
        )


def _extract_output_text(response: Mapping[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                raise OpenAIResponsesError("OpenAI refused the maintenance request")
            text = content.get("text")
            if content.get("type") == "output_text" and isinstance(text, str) and text.strip():
                return text
    raise OpenAIResponsesError("OpenAI response has no structured output text")


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
        error_code, error_type = _safe_http_error_details(exc)
        detail = error_code or error_type
        suffix = f" ({detail})" if detail else ""
        raise OpenAIResponsesError(
            f"OpenAI Responses API returned HTTP {exc.code}{suffix}",
            status_code=exc.code,
            error_code=error_code,
            error_type=error_type,
        ) from exc
    except URLError as exc:
        raise OpenAIResponsesError("OpenAI Responses API transport failed") from exc
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OpenAIResponsesError("OpenAI Responses API returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise OpenAIResponsesError("OpenAI Responses API returned a non-object payload")
    return decoded


def _safe_http_error_details(error: HTTPError) -> tuple[str | None, str | None]:
    """Extract only provider error classification; discard raw body and message."""

    try:
        body = error.read(16_384).decode("utf-8", errors="replace")
        decoded = json.loads(body)
        detail = decoded.get("error", {}) if isinstance(decoded, dict) else {}
    except (AttributeError, json.JSONDecodeError, OSError):
        return None, None
    if not isinstance(detail, dict):
        return None, None
    code = detail.get("code")
    error_type = detail.get("type")
    return (
        code if isinstance(code, str) and len(code) <= 120 else None,
        error_type if isinstance(error_type, str) and len(error_type) <= 120 else None,
    )
