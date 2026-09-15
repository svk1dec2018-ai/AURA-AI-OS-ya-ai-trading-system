from __future__ import annotations

import json
import socket
import threading
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from aura.interface.operator_read_model import OperatorReadModel, ReadDomain
from aura.interface.web_command_center import CommandCenterConfig
from aura.interface.web_command_center_v2 import CommandCenterV2Service

OWNER_TOKEN = "owner-token-with-at-least-32-characters"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request_json(
    url: str,
    *,
    text: str | None = None,
    token: str | None = None,
):
    data = None
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    method = "GET"
    if text is not None:
        data = json.dumps({"text": text}).encode()
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())
    with response:
        return response.status, json.loads(response.read())


def _service(
    tmp_path: Path,
    read_model: OperatorReadModel | None = None,
    *,
    token: str | None = None,
):
    service = CommandCenterV2Service(
        CommandCenterConfig(
            port=_free_port(),
            queue_path=tmp_path / "research.jsonl",
            api_token=token,
        ),
        read_model=read_model,
    )
    server = service.make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return service, server, thread


def test_v2_unattached_domains_fail_closed(tmp_path: Path) -> None:
    service = CommandCenterV2Service(
        CommandCenterConfig(queue_path=tmp_path / "research.jsonl")
    )
    status, payload = service.handle_command("scan markets")
    assert status == HTTPStatus.SERVICE_UNAVAILABLE
    assert payload["accepted"] is False
    assert payload["payload"]["available"] is False
    assert payload["payload"]["reason"] == "source not attached"


def test_v2_returns_only_fresh_governed_domain_snapshots(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = OperatorReadModel()
    store.publish(
        ReadDomain.RISK,
        {"kill_switch": False, "drawdown_pct": "0.75"},
        source="risk-engine:v1",
        observed_at=now,
        received_at=now,
        max_age=timedelta(minutes=1),
    )
    service = CommandCenterV2Service(
        CommandCenterConfig(queue_path=tmp_path / "research.jsonl"),
        read_model=store,
    )
    status, payload = service.handle_command("risk status")
    assert status == HTTPStatus.OK
    assert payload["accepted"] is True
    assert payload["payload"]["source"] == "risk-engine:v1"
    assert payload["payload"]["payload"]["kill_switch"] is False


def test_v2_explain_is_deterministic_from_current_radar(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = OperatorReadModel()
    store.publish(
        ReadDomain.OPPORTUNITIES,
        {
            "as_of": now.isoformat(),
            "count": 1,
            "actionable_count": 1,
            "items": [
                {
                    "rank": 1,
                    "symbol": "BTC/USD",
                    "intent": "LONG",
                    "score": 88.2,
                    "rationale": "CEO evidence fusion supports the long case",
                    "risk_flags": [],
                }
            ],
        },
        source="aura-opportunity-radar",
        observed_at=now,
        received_at=now,
        max_age=timedelta(minutes=1),
    )
    service = CommandCenterV2Service(
        CommandCenterConfig(queue_path=tmp_path / "research.jsonl"),
        read_model=store,
    )
    status, payload = service.handle_command("explain for BTC/USD")
    assert status == HTTPStatus.OK
    assert payload["accepted"] is True
    assert payload["payload"]["opportunity"]["symbol"] == "BTC/USD"
    assert payload["payload"]["opportunity"]["score"] == 88.2


def test_v2_still_hard_blocks_paper_and_live_control(tmp_path: Path) -> None:
    service = CommandCenterV2Service(
        CommandCenterConfig(queue_path=tmp_path / "research.jsonl")
    )
    paper_status, paper = service.handle_command("paper start")
    live_status, live = service.handle_command("go live")
    assert paper_status == HTTPStatus.FORBIDDEN
    assert paper["accepted"] is False
    assert live_status == HTTPStatus.FORBIDDEN
    assert live["accepted"] is False
    assert live["human_live_approval_required"] is True


def test_v2_http_exposes_read_model_and_cockpit_assets(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = OperatorReadModel()
    store.publish(
        ReadDomain.PORTFOLIO,
        {"equity": "100000", "unrealized_pnl": "125"},
        source="portfolio-ledger:v1",
        observed_at=now,
        received_at=now,
        max_age=timedelta(minutes=1),
    )
    _svc, server, thread = _service(tmp_path, store)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, portfolio = _request_json(base + "/api/portfolio")
        assert status == HTTPStatus.OK
        assert portfolio["available"] is True
        assert portfolio["payload"]["equity"] == "100000"

        status, missing = _request_json(base + "/api/opportunities")
        assert status == HTTPStatus.SERVICE_UNAVAILABLE
        assert missing["available"] is False
        assert missing["payload"] is None

        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode()
            assert "Opportunity Radar" in html
            assert "No broker order controls" in html
            assert response.headers["X-Frame-Options"] == "DENY"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_v2_status_reports_domain_sources_without_fabricating_data(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = OperatorReadModel()
    store.publish(
        ReadDomain.RISK,
        {"kill_switch": False},
        source="risk-engine:v1",
        observed_at=now,
        received_at=now,
        max_age=timedelta(minutes=1),
    )
    service = CommandCenterV2Service(
        CommandCenterConfig(queue_path=tmp_path / "research.jsonl"),
        read_model=store,
    )
    status = service.status()
    assert status["ui_version"] == 2
    assert status["risk_source"] == "risk-engine:v1"
    assert status["market_data_source"] == "not_attached"
    assert status["portfolio_source"] == "not_attached"
    assert status["live_money_enabled"] is False


def test_v2_requires_owner_auth_for_research_but_not_read_commands(tmp_path: Path) -> None:
    service = CommandCenterV2Service(
        CommandCenterConfig(
            queue_path=tmp_path / "research.jsonl",
            api_token=OWNER_TOKEN,
            owner_id="primary-owner",
        )
    )

    read_status, _ = service.handle_command("system status")
    denied_status, denied = service.handle_command("research NIFTY breadth")
    accepted_status, accepted = service.handle_command(
        "research NIFTY breadth",
        owner_authenticated=True,
    )

    assert read_status == HTTPStatus.OK
    assert denied_status == HTTPStatus.UNAUTHORIZED
    assert denied["accepted"] is False
    assert accepted_status == HTTPStatus.ACCEPTED
    assert accepted["payload"]["auto_promotion_allowed"] is False
    queued = (tmp_path / "research.jsonl").read_text(encoding="utf-8")
    assert '"authenticated_owner_id":"primary-owner"' in queued
    assert OWNER_TOKEN not in queued


def test_v2_http_owner_token_and_session_only_pwa(tmp_path: Path) -> None:
    _svc, server, thread = _service(tmp_path, token=OWNER_TOKEN)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        missing, _ = _request_json(base + "/api/command", text="research BTC")
        wrong, _ = _request_json(
            base + "/api/command",
            text="research BTC",
            token="wrong-token-with-at-least-32-characters",
        )
        accepted, result = _request_json(
            base + "/api/command",
            text="research BTC",
            token=OWNER_TOKEN,
        )
        assert missing == HTTPStatus.UNAUTHORIZED
        assert wrong == HTTPStatus.UNAUTHORIZED
        assert accepted == HTTPStatus.ACCEPTED
        assert result["payload"]["status"] == "pending_human_review"

        with urlopen(base + "/", timeout=3) as response:
            html = response.read().decode()
        with urlopen(base + "/v2-app.js", timeout=3) as response:
            javascript = response.read().decode()
        assert 'id="owner-token"' in html
        assert "sessionStorage" in javascript
        assert "localStorage" not in javascript
        assert "Authorization" in javascript
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
