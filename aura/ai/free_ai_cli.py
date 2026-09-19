from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aura.ai.free_models import free_ai_catalog_payload, get_free_ai_preset
from aura.ai.ollama_structured import normalize_local_ollama_url

TagsLoader = Callable[[str, float], dict[str, Any]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aura-free-ai",
        description="Inspect AURA's key-free local five-model Ollama preset",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    catalog = subparsers.add_parser("catalog", help="print curated model and safety metadata")
    catalog.add_argument("--preset", default="balanced5")
    probe = subparsers.add_parser(
        "probe",
        help="check which curated models are installed in local Ollama",
    )
    probe.add_argument("--preset", default="balanced5")
    probe.add_argument(
        "--url",
        default=os.getenv("AURA_OLLAMA_URL", "http://127.0.0.1:11434"),
    )
    probe.add_argument("--timeout-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "catalog":
            _emit(free_ai_catalog_payload(args.preset))
            return 0
        if args.command == "probe":
            payload = probe_local_models(
                preset_name=args.preset,
                base_url=args.url,
                timeout_seconds=args.timeout_seconds,
            )
            _emit(payload)
            return 0 if payload["ready"] else 1
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
        return 2
    return 2


def probe_local_models(
    *,
    preset_name: str = "balanced5",
    base_url: str = "http://127.0.0.1:11434",
    timeout_seconds: float = 5.0,
    tags_loader: TagsLoader | None = None,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    normalized_url = normalize_local_ollama_url(base_url)
    expected = tuple(profile.model_id for profile in get_free_ai_preset(preset_name))
    payload = (tags_loader or _default_tags_loader)(
        f"{normalized_url}/api/tags",
        timeout_seconds,
    )
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        raise TypeError("local Ollama tags response is missing its model list")
    installed = tuple(
        dict.fromkeys(
            name
            for item in raw_models
            if isinstance(item, dict)
            for name in (_model_name(item),)
            if name
        )
    )
    installed_set = set(installed)
    missing = tuple(model for model in expected if model not in installed_set)
    return {
        "ok": True,
        "ready": not missing,
        "preset": preset_name,
        "ollama_url": normalized_url,
        "required_models": expected,
        "installed_required_models": tuple(
            model for model in expected if model in installed_set
        ),
        "missing_models": missing,
        "install_commands": tuple(f"ollama pull {model}" for model in missing),
        "credentials_used": False,
        "cloud_models_used": False,
        "fund_operations_available": False,
        "risk_bypass_available": False,
    }


def _model_name(item: dict[str, Any]) -> str:
    for key in ("name", "model"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _default_tags_loader(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"local Ollama tags API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("local Ollama tags API is unreachable") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("local Ollama tags API returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("local Ollama tags API returned a non-object payload")
    return payload


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
