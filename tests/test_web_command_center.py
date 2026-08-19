from __future__ import annotations

import json
import threading
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from aura.interface.web_command_center import (
    CommandCenterConfig,
    CommandCenterService,
    DurableResearchQueue,
)


def _request_json(url: str, *, text: str | None = None, key: str | None = None):
    headers = {}
    data = None
    if text is not None:
        headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        data = json.dumps({"text": text}).encode()
    request = Request(
        url,
        data=data,
        headers=headers,
        method="POST" if data else "GET",
    )
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())
    with response:
        return response.status, json.loads(response.read())


def _running_service(tmp_path: Path):
    service = CommandCenterService(
        CommandCenterConfig(port=1, queue_path=tmp_path / "queue.jsonl")
    )
    server = service.make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return service, server, thread


def test_non_loopback_binding_requires_strong_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-loopback"):
        CommandCenterConfig(host="0.0.0.0", queue_path=tmp_path / "q")
    CommandCenterConfig(
        host="0.0.0.0",
        api_token="x" * 32,
        queue_path=tmp_path / "q",
    )


def test_research_queue_is_restart_safe_and_idempotent(tmp_path: Path) -> None:
    service = CommandCenterService(
        CommandCenterConfig(queue_path=tmp_path / "queue.jsonl")
    )
    status1, first = service.handle_command(
        "research XAUUSD regime filters",
        idempotency_key="same",
    )
    status2, second = service.handle_command(
        "research XAUUSD regime filters",
        idempotency_key="same",
    )
    assert status1 == HTTPStatus.ACCEPTED
    assert status2 == HTTPStatus.ACCEPTED
    assert first["payload"]["request_id"] == second["payload"]["request_id"]
    assert service.queue.count == 1
    restarted = DurableResearchQueue(tmp_path / "queue.jsonl")
    assert restarted.count == 1


def test_queue_corruption_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "queue.jsonl"
    service = CommandCenterService(CommandCenterConfig(queue_path=path))
    service.handle_command("research BTC regime", idempotency_key="a")
    line = json.loads(path.read_text())
    line["raw_text"] = "tampered"
    path.write_text(json.dumps(line) + "\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        DurableResearchQueue(path)


def test_live_and_paper_commands_are_blocked_before_execution(tmp_path: Path) -> None:
    service = CommandCenterService(
        CommandCenterConfig(queue_path=tmp_path / "queue.jsonl")
    )
    live_status, live = service.handle_command("go live and place live trade")
    paper_status, paper = service.handle_command("paper start")
    assert live_status == HTTPStatus.FORBIDDEN
    assert live["accepted"] is False
    assert live["human_live_approval_required"] is True
    assert paper_status == HTTPStatus.FORBIDDEN
    assert paper["accepted"] is False


def test_unattached_market_source_returns_no_fabricated_data(tmp_path: Path) -> None:
    service = CommandCenterService(
        CommandCenterConfig(queue_path=tmp_path / "queue.jsonl")
    )
    status, result = service.handle_command("scan market for XAUUSD")
    assert status == HTTPStatus.SERVICE_UNAVAILABLE
    assert result["payload"] == {"source_available": False}
    assert "no market" in result["summary"]


def test_http_status_research_and_live_boundary(tmp_path: Path) -> None:
    _service, server, thread = _running_service(tmp_path)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, snapshot = _request_json(base + "/api/status")
        assert status == HTTPStatus.OK
        assert snapshot["live_money_enabled"] is False
        research_status, research = _request_json(
            base + "/api/command",
            text="research NIFTY regime filter",
            key="stable-key",
        )
        assert research_status == HTTPStatus.ACCEPTED
        assert research["payload"]["auto_promotion_allowed"] is False
        live_status, live = _request_json(base + "/api/command", text="go live")
        assert live_status == HTTPStatus.FORBIDDEN
        assert live["accepted"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_pwa_assets_are_served_with_security_headers(tmp_path: Path) -> None:
    _service, server, thread = _running_service(tmp_path)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode()
            assert "AURA AI OS" in html
            assert response.headers["X-Frame-Options"] == "DENY"
            assert "default-src 'self'" in response.headers["Content-Security-Policy"]
        with urlopen(base + "/manifest.webmanifest", timeout=3) as response:
            manifest = json.loads(response.read())
            assert manifest["display"] == "standalone"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
