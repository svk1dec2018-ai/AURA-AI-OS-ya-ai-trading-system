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

from aura.ai.free_models import parse_ollama_keep_alive
from aura.ai.openai_responses import StructuredResponse

JsonTransport = Callable[[str, dict[str, Any], float], Awaitable[dict[str, Any]]]

_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "host.docker.internal"}


class OllamaStructuredError(RuntimeError):
    """Safe local Ollama structured-output failure."""


class OllamaStructuredHTTPError(OllamaStructuredError):
    def __init__(self, status_code: int, response_body: str = "") -> None:
        self.status_code = status_code
        detail = _safe_error_detail(response_body)
        suffix = f": {detail}" if detail else ""
        super().__init__(f"local Ollama API returned HTTP {status_code}{suffix}")


class OllamaStructuredClient:
    """Dependency-free structured client restricted to a local Ollama server.

    It has no API key, cloud endpoint, filesystem, shell, broker, fund, approval or
    deployment capability. Callers still validate the returned schema and enforce
    AURA's owner-gated change-control policy.
    """

    provider_id = "ollama"

    def __init__(
        self,
        model_id: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 120.0,
        think: bool | str = False,
        keep_alive: str | int = 0,
        transport: JsonTransport | None = None,
        request_limiter: asyncio.Semaphore | None = None,
    ) -> None:
        normalized_model = model_id.strip()
        if _MODEL_ID_PATTERN.fullmatch(normalized_model) is None:
            raise ValueError("invalid Ollama model_id")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.model_id = normalized_model
        self.base_url = normalize_local_ollama_url(base_url)
        self.timeout_seconds = timeout_seconds
        self.think = think
        self.keep_alive = parse_ollama_keep_alive(keep_alive)
        self._transport = transport or _default_json_transport
        self._request_limiter = request_limiter

    def __repr__(self) -> str:
        return (
            f"OllamaStructuredClient(model_id={self.model_id!r}, "
            f"base_url={self.base_url!r}, timeout_seconds={self.timeout_seconds!r})"
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
        schema_payload = dict(schema)
        prompt = {
            "schema_name": schema_name,
            "input": dict(user_payload),
            "output_schema": schema_payload,
        }
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
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
            ],
            "stream": False,
            "format": schema_payload,
            "options": {"temperature": 0},
            "keep_alive": self.keep_alive,
        }
        if self.think is not False:
            payload["think"] = self.think
        response = await self._request_with_compatibility(payload)
        output_text = _extract_message_content(response)
        try:
            output = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OllamaStructuredError("Ollama returned invalid structured JSON") from exc
        if not isinstance(output, dict):
            raise OllamaStructuredError("Ollama structured output must be a JSON object")
        returned_model = response.get("model")
        audited_model = returned_model if isinstance(returned_model, str) else self.model_id
        response_digest = hashlib.sha256(
            json.dumps(
                {
                    "model": audited_model,
                    "output": output,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return StructuredResponse(
            response_id=f"ollama:{response_digest[:40]}",
            model_id=audited_model,
            output=output,
        )

    async def _request_with_compatibility(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._request_limiter is None:
            return await self._send_with_compatibility(payload)
        async with self._request_limiter:
            return await self._send_with_compatibility(payload)

    async def _send_with_compatibility(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/api/chat"
        try:
            return await self._transport(url, payload, self.timeout_seconds)
        except OllamaStructuredHTTPError as exc:
            if exc.status_code != 400:
                raise
        fallback = dict(payload)
        fallback.pop("think", None)
        fallback["format"] = "json"
        try:
            return await self._transport(url, fallback, self.timeout_seconds)
        except OllamaStructuredError as exc:
            raise OllamaStructuredError(
                f"Ollama compatibility retry failed: {exc}"
            ) from exc


def normalize_local_ollama_url(base_url: str) -> str:
    """Allow only AURA's loopback or Docker-host Ollama endpoint."""

    parsed = urlsplit(base_url.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _LOCAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            "AURA Ollama URL must be a credential-free local HTTP endpoint"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("AURA Ollama URL contains an invalid port") from exc
    netloc = parsed.hostname or ""
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit(("http", netloc, "", "", ""))


def _extract_message_content(response: Mapping[str, Any]) -> str:
    message = response.get("message")
    if not isinstance(message, dict):
        raise OllamaStructuredError("Ollama response is missing its message object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise OllamaStructuredError("Ollama response has no structured output text")
    return content


async def _default_json_transport(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    return await asyncio.to_thread(_sync_json_post, url, payload, timeout_seconds)


def _sync_json_post(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        try:
            response_body = exc.read(16_384).decode("utf-8", errors="replace")
        except OSError:
            response_body = ""
        raise OllamaStructuredHTTPError(exc.code, response_body) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise OllamaStructuredError("local Ollama API transport failed") from exc
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OllamaStructuredError("local Ollama API returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise OllamaStructuredError("local Ollama API returned a non-object payload")
    return decoded


def _safe_error_detail(response_body: str, *, max_chars: int = 240) -> str:
    if not response_body.strip():
        return ""
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), str):
        return ""
    return payload["error"].strip()[:max_chars]
