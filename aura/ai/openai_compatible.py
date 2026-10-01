from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from aura.ai.openai_responses import StructuredResponse

JsonTransport = Callable[
    [str, dict[str, Any], Mapping[str, str], float],
    Awaitable[dict[str, Any]],
]

_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "host.docker.internal"}
_ALLOWED_CLOUD_HOSTS = {"openrouter.ai"}


class CompatibleStructuredError(RuntimeError):
    """Safe OpenAI-compatible gateway failure without leaking secrets."""


class CompatibleHTTPError(CompatibleStructuredError):
    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        suffix = f": {detail}" if detail else ""
        super().__init__(f"compatible AI gateway returned HTTP {status_code}{suffix}")


class OpenAICompatibleStructuredClient:
    """Structured JSON client for OmniRoute, OpenRouter and local compatible gateways."""

    provider_id = "compatible"

    def __init__(
        self,
        model_id: str,
        *,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float = 120.0,
        transport: JsonTransport | None = None,
        request_limiter: asyncio.Semaphore | None = None,
    ) -> None:
        normalized_model = model_id.strip()
        if _MODEL_ID_PATTERN.fullmatch(normalized_model) is None:
            raise ValueError("invalid compatible model_id")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.model_id = normalized_model
        self.base_url, local = normalize_compatible_base_url(base_url)
        key = api_key.strip()
        if not local and not key:
            raise ValueError("cloud compatible gateway requires an API key")
        self.timeout_seconds = timeout_seconds
        self._api_key = key
        self._transport = transport or _default_json_transport
        self._request_limiter = request_limiter

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleStructuredClient(model_id={self.model_id!r}, "
            f"base_url={self.base_url!r}, timeout_seconds={self.timeout_seconds!r}, "
            "api_key=<redacted>)"
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

        prompt = {
            "schema_name": schema_name,
            "input": dict(user_payload),
            "output_schema": dict(schema),
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    prompt,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            },
        ]
        strict_payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": 0,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": dict(schema),
                },
            },
        }
        try:
            response = await self._request(strict_payload)
        except CompatibleHTTPError as exc:
            if exc.status_code not in {400, 404, 422}:
                raise
            fallback = {
                "model": self.model_id,
                "messages": messages,
                "temperature": 0,
                "stream": False,
                "response_format": {"type": "json_object"},
            }
            response = await self._request(fallback)

        output_text = _extract_content(response)
        try:
            output = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise CompatibleStructuredError(
                "compatible AI gateway returned invalid structured JSON"
            ) from exc
        if not isinstance(output, dict):
            raise CompatibleStructuredError(
                "compatible AI structured output must be a JSON object"
            )

        returned_model = response.get("model")
        audited_model = returned_model if isinstance(returned_model, str) else self.model_id
        response_id = response.get("id")
        if not isinstance(response_id, str) or not response_id.strip():
            digest = hashlib.sha256(
                json.dumps(
                    {"model": audited_model, "output": output},
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            response_id = f"compatible:{digest[:40]}"
        return StructuredResponse(
            response_id=response_id,
            model_id=audited_model,
            output=output,
        )

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        url = f"{self.base_url}/chat/completions"
        if self._request_limiter is None:
            return await self._transport(url, payload, headers, self.timeout_seconds)
        async with self._request_limiter:
            return await self._transport(url, payload, headers, self.timeout_seconds)


def normalize_compatible_base_url(base_url: str) -> tuple[str, bool]:
    parsed = urlsplit(base_url.strip())
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("compatible AI base URL cannot include credentials/query/fragment")
    host = (parsed.hostname or "").lower()
    local = host in _LOCAL_HOSTS
    if local:
        if parsed.scheme != "http":
            raise ValueError("local compatible AI gateway must use HTTP")
    else:
        if parsed.scheme != "https" or host not in _ALLOWED_CLOUD_HOSTS:
            raise ValueError("cloud compatible AI host is not allowlisted")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("compatible AI base URL contains an invalid port") from exc
    netloc = parsed.hostname or ""
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1"
    return urlunsplit((parsed.scheme, netloc, path, "", "")), local


def _extract_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise CompatibleStructuredError("compatible AI response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise CompatibleStructuredError("compatible AI response choice is invalid")
    message = first.get("message")
    if not isinstance(message, dict):
        raise CompatibleStructuredError("compatible AI response is missing message")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        texts = [
            str(item.get("text"))
            for item in content
            if isinstance(item, dict)
            and item.get("type") in {"text", "output_text"}
            and isinstance(item.get("text"), str)
        ]
        joined = "".join(texts).strip()
        if joined:
            return joined
    raise CompatibleStructuredError("compatible AI response has no content")


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
        detail = _safe_error_detail(exc)
        raise CompatibleHTTPError(exc.code, detail) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise CompatibleStructuredError("compatible AI gateway transport failed") from exc
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CompatibleStructuredError("compatible AI gateway returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise CompatibleStructuredError("compatible AI gateway returned a non-object payload")
    return decoded


def _safe_error_detail(error: HTTPError) -> str:
    try:
        body = error.read(16_384).decode("utf-8", errors="replace")
        payload = json.loads(body)
    except (AttributeError, json.JSONDecodeError, OSError):
        return ""
    if not isinstance(payload, dict):
        return ""
    raw = payload.get("error")
    if isinstance(raw, dict):
        value = raw.get("code") or raw.get("type")
    else:
        value = raw
    return str(value)[:120] if value else ""
