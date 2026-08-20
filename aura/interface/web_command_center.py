from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aura.interface.command_center import AssistantCommand, AssistantIntent, CommandRouter

_MAX_BODY_BYTES = 16 * 1024
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_OWNER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:@-]{1,80}$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _checksum(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class CommandCenterConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    queue_path: Path = Path("artifacts/operator/research_requests.jsonl")
    api_token: str | None = None
    owner_id: str = "owner"
    max_body_bytes: int = _MAX_BODY_BYTES

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.max_body_bytes < 256 or self.max_body_bytes > 1024 * 1024:
            raise ValueError("max_body_bytes must be between 256 bytes and 1 MiB")
        token = self.api_token or ""
        if token and len(token) < 32:
            raise ValueError("configured API token must contain at least 32 characters")
        if self.host not in _LOOPBACK_HOSTS and not token:
            raise ValueError("non-loopback binding requires an API token of at least 32 characters")
        if _OWNER_ID_PATTERN.fullmatch(self.owner_id) is None:
            raise ValueError("owner_id must contain 1-80 safe identifier characters")


class DurableResearchQueue:
    """Checksummed append-only queue for owner research/change requests.

    The queue stores only the SHA-256 digest of an idempotency key. On restart,
    every record is verified before it is accepted into the in-memory index.
    Corrupt or partially-written records fail closed instead of being skipped.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []
        self._idempotency_index: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line_number, raw_line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"research queue has invalid JSON at line {line_number}") from exc
            claimed = record.pop("checksum", None)
            if not isinstance(claimed, str) or not hmac.compare_digest(claimed, _checksum(record)):
                raise ValueError(f"research queue checksum mismatch at line {line_number}")
            record["checksum"] = claimed
            self._records.append(record)
            key_hash = record.get("idempotency_key_sha256")
            if isinstance(key_hash, str) and key_hash:
                self._idempotency_index[key_hash] = record

    @property
    def count(self) -> int:
        return len(self._records)

    def enqueue(
        self,
        command: AssistantCommand,
        *,
        owner_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if command.intent is not AssistantIntent.RESEARCH_REQUEST:
            raise ValueError("only research requests may be queued")
        key_hash = (
            hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
            if idempotency_key
            else None
        )
        with self._lock:
            if key_hash and key_hash in self._idempotency_index:
                return dict(self._idempotency_index[key_hash])
            body: dict[str, Any] = {
                "request_id": f"research:{command.command_id.removeprefix('cmd:')}",
                "command_id": command.command_id,
                "authenticated_owner_id": owner_id,
                "raw_text": command.raw_text,
                "parameters": command.parameters,
                "created_at": command.created_at.isoformat(),
                "queued_at": _now_iso(),
                "status": "pending_human_review",
                "auto_promotion_allowed": False,
                "idempotency_key_sha256": key_hash,
            }
            record = {**body, "checksum": _checksum(body)}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        record,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            self._records.append(record)
            if key_hash:
                self._idempotency_index[key_hash] = record
            return dict(record)


class CommandCenterService:
    """Local-first operator PWA/API boundary.

    This surface intentionally has no broker order-submit capability. LIVE and
    PAPER control intents are blocked before router execution. Read-only market,
    risk and portfolio requests return an explicit source-unavailable response
    until a governed provider is wired, preventing fabricated operator data.
    """

    def __init__(
        self,
        config: CommandCenterConfig | None = None,
        *,
        router: CommandRouter | None = None,
    ) -> None:
        self.config = config or CommandCenterConfig()
        self.router = router or CommandRouter(
            allow_paper_control=False,
            allow_live_control=False,
        )
        self.queue = DurableResearchQueue(self.config.queue_path)
        self.started_at = _now_iso()

    def status(self) -> dict[str, Any]:
        return {
            "service": "aura-command-center",
            "status": "ready",
            "execution_mode": "paper_research_only",
            "live_money_enabled": False,
            "paper_control_exposed": False,
            "owner_auth_configured": self.config.api_token is not None,
            "market_data_source": "not_attached",
            "risk_source": "not_attached",
            "portfolio_source": "not_attached",
            "queued_research_requests": self.queue.count,
            "started_at": self.started_at,
            "updated_at": _now_iso(),
        }

    def handle_command(
        self,
        text: str,
        *,
        owner_authenticated: bool = False,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        command = self.router.parse(text)
        if command.intent is AssistantIntent.LIVE_CONTROL:
            return HTTPStatus.FORBIDDEN, {
                "accepted": False,
                "command_id": command.command_id,
                "intent": command.intent.value,
                "summary": "live-money control is not exposed by the command center",
                "risk_gate_required": True,
                "human_live_approval_required": True,
            }
        if command.intent is AssistantIntent.PAPER_CONTROL:
            return HTTPStatus.FORBIDDEN, {
                "accepted": False,
                "command_id": command.command_id,
                "intent": command.intent.value,
                "summary": (
                    "paper execution control is not exposed by this observation/research surface"
                ),
                "risk_gate_required": True,
            }
        if command.intent is AssistantIntent.RESEARCH_REQUEST:
            if self.config.api_token is None or not owner_authenticated:
                return HTTPStatus.UNAUTHORIZED, {
                    "accepted": False,
                    "command_id": command.command_id,
                    "intent": command.intent.value,
                    "summary": "authenticated owner token required for research requests",
                }
            record = self.queue.enqueue(
                command,
                owner_id=self.config.owner_id,
                idempotency_key=idempotency_key,
            )
            return HTTPStatus.ACCEPTED, {
                "accepted": True,
                "command_id": command.command_id,
                "intent": command.intent.value,
                "summary": "research request queued for governed human review",
                "payload": {
                    "request_id": record["request_id"],
                    "status": record["status"],
                    "auto_promotion_allowed": False,
                },
            }
        if command.intent is AssistantIntent.STATUS:
            return HTTPStatus.OK, {
                "accepted": True,
                "command_id": command.command_id,
                "intent": command.intent.value,
                "summary": "command center status",
                "payload": self.status(),
            }
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "accepted": False,
            "command_id": command.command_id,
            "intent": command.intent.value,
            "summary": (
                "governed data source is not attached; no market, risk, or portfolio data "
                "was fabricated"
            ),
            "payload": {"source_available": False},
        }

    def make_server(self) -> ThreadingHTTPServer:
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AURACommandCenter/1.0"

            def log_message(self, format: str, *args: object) -> None:
                return

            def _headers(self, status: int, content_type: str, length: int) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; img-src 'self' data:; manifest-src 'self'; "
                    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                )
                self.end_headers()

            def _write(self, status: int, body: bytes, content_type: str) -> None:
                self._headers(status, content_type, len(body))
                self.wfile.write(body)

            def _json(self, status: int, payload: Mapping[str, Any]) -> None:
                self._write(
                    status,
                    _canonical_json(payload),
                    "application/json; charset=utf-8",
                )

            def _authorized(self) -> bool:
                expected = service.config.api_token
                if not expected:
                    return True
                supplied = self.headers.get("Authorization", "")
                return hmac.compare_digest(supplied, f"Bearer {expected}")

            def _owner_authenticated(self) -> bool:
                return service.config.api_token is not None and self._authorized()

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path.startswith("/api/") and not self._authorized():
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                assets = {
                    "/": (_INDEX_HTML, "text/html; charset=utf-8"),
                    "/app.js": (_APP_JS, "text/javascript; charset=utf-8"),
                    "/styles.css": (_STYLES_CSS, "text/css; charset=utf-8"),
                    "/manifest.webmanifest": (
                        _MANIFEST,
                        "application/manifest+json; charset=utf-8",
                    ),
                    "/sw.js": (_SERVICE_WORKER, "text/javascript; charset=utf-8"),
                }
                if path in assets:
                    text, content_type = assets[path]
                    self._write(HTTPStatus.OK, text.encode("utf-8"), content_type)
                    return
                if path in {"/api/health", "/api/status"}:
                    self._json(HTTPStatus.OK, service.status())
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                if path != "/api/command":
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                if not self._authorized():
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                length_header = self.headers.get("Content-Length")
                if not length_header or not length_header.isdigit():
                    self._json(
                        HTTPStatus.LENGTH_REQUIRED,
                        {"error": "content_length_required"},
                    )
                    return
                length = int(length_header)
                if length > service.config.max_body_bytes:
                    self._json(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        {"error": "request_too_large"},
                    )
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                    return
                text = payload.get("text") if isinstance(payload, dict) else None
                if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "text_must_be_1_to_4000_characters"},
                    )
                    return
                key = self.headers.get("Idempotency-Key")
                if key is not None and not 1 <= len(key) <= 200:
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid_idempotency_key"},
                    )
                    return
                status, result = service.handle_command(
                    text,
                    owner_authenticated=self._owner_authenticated(),
                    idempotency_key=key,
                )
                self._json(status, result)

        return ThreadingHTTPServer((self.config.host, self.config.port), Handler)

    def run_forever(self) -> None:
        server = self.make_server()
        try:
            server.serve_forever()
        finally:
            server.server_close()


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#07111f">
<title>AURA Command Center</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="stylesheet" href="/styles.css">
</head>
<body>
<main>
<header>
<div>
<p class="eyebrow">AURA AI OS</p>
<h1>Command Center</h1>
<p class="sub">Owner-controlled paper research surface. Live money is disabled here.</p>
</div>
<span id="health" class="pill">connecting</span>
</header>
<section class="grid">
<article><span>Execution</span><strong id="mode">—</strong><small>HTTP trading controls are blocked.</small></article>
<article><span>Research queue</span><strong id="queue">—</strong><small>Durable, checksummed requests.</small></article>
<article><span>Market data</span><strong id="market">—</strong><small>No synthetic values are shown.</small></article>
<article><span>Risk source</span><strong id="risk">—</strong><small>Independent risk remains authoritative.</small></article>
</section>
<section class="console">
<div class="owner-auth">
<label for="owner-token">Owner token</label>
<input id="owner-token" type="password" minlength="32" autocomplete="current-password" placeholder="Required for research/change requests">
<button id="save-token" type="button">Use for this session</button>
<button id="clear-token" type="button">Clear</button>
<small>Kept only in this browser tab session; never written to AURA storage.</small>
</div>
<div class="console-head">
<div><h2>Talk to AURA</h2><p>Try “system status” or “research XAUUSD regime filters”.</p></div>
<button id="mic" type="button" aria-label="Start voice input">🎙 Voice</button>
</div>
<form id="command-form">
<input id="command" maxlength="4000" autocomplete="off" placeholder="Hi AURA, system status…" aria-label="Command">
<button type="submit">Send</button>
</form>
<pre id="result" aria-live="polite">Ready.</pre>
</section>
<footer>Observation + governed research only · no broker credentials in the browser</footer>
</main>
<script src="/app.js" defer></script>
</body>
</html>"""

_STYLES_CSS = """:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#e7eef8;background:#050b14;color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 20% 0,#132c47 0,transparent 38%),#050b14}main{width:min(1040px,calc(100% - 32px));margin:auto;padding:32px 0 48px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:24px}.eyebrow{letter-spacing:.18em;text-transform:uppercase;color:#7dd3fc;font-size:.75rem;margin:0 0 6px}h1{font-size:clamp(2rem,7vw,4.4rem);line-height:.96;margin:0}.sub{color:#9fb0c7;max-width:620px}.pill{border:1px solid #2b4664;border-radius:999px;padding:8px 12px;color:#93c5fd}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.grid article,.console{background:#0b1522cc;border:1px solid #1f3248;border-radius:18px;box-shadow:0 16px 40px #0006}.grid article{padding:18px;min-height:142px;display:flex;flex-direction:column;gap:8px}.grid span,.grid small,.console p,footer,.owner-auth small{color:#91a4bb}.grid strong{font-size:1.2rem;margin-top:auto}.console{margin-top:16px;padding:20px}.owner-auth{display:grid;grid-template-columns:auto 1fr auto auto;gap:10px;align-items:center;padding-bottom:18px;margin-bottom:18px;border-bottom:1px solid #1f3248}.owner-auth small{grid-column:2/-1}.console-head{display:flex;justify-content:space-between;gap:14px;align-items:center}.console h2{margin:0}.console p{margin:.35rem 0 0}form{display:flex;gap:10px;margin-top:18px}input,button{font:inherit;border-radius:12px;border:1px solid #2b4664}input{flex:1;min-width:0;background:#07111f;color:#eef6ff;padding:14px}button{cursor:pointer;background:#102c46;color:#eaf6ff;padding:12px 16px}button:hover{background:#173b5c}pre{white-space:pre-wrap;word-break:break-word;background:#050b14;border-radius:12px;padding:14px;min-height:112px;color:#c7dbf2;overflow:auto}footer{text-align:center;margin-top:22px;font-size:.85rem}@media(max-width:760px){main{width:min(100% - 20px,1040px);padding-top:18px}.grid{grid-template-columns:repeat(2,1fr)}header{flex-direction:column}.console-head{align-items:flex-start}.owner-auth{grid-template-columns:1fr}.owner-auth small{grid-column:1}form{flex-direction:column}}@media(max-width:420px){.grid{grid-template-columns:1fr}}"""

_APP_JS = """const $=s=>document.querySelector(s);const token=()=>sessionStorage.getItem('auraOwnerToken')||'';const authHeaders=()=>token()?{'Authorization':'Bearer '+token()}:{};async function refresh(){try{const r=await fetch('/api/status',{cache:'no-store',headers:authHeaders()});if(!r.ok)throw new Error('status '+r.status);const s=await r.json();$('#health').textContent='online';$('#mode').textContent=s.execution_mode;$('#queue').textContent=String(s.queued_research_requests);$('#market').textContent=s.market_data_source;$('#risk').textContent=s.risk_source}catch(e){$('#health').textContent='locked/offline';$('#result').textContent='Status error: '+e.message}}async function send(text){$('#result').textContent='Working…';const key=crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random();try{const r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key,...authHeaders()},body:JSON.stringify({text})});const p=await r.json();$('#result').textContent=JSON.stringify(p,null,2);await refresh()}catch(e){$('#result').textContent='Command error: '+e.message}}$('#save-token').addEventListener('click',()=>{const value=$('#owner-token').value;if(value.length<32){$('#result').textContent='Owner token must contain at least 32 characters.';return}sessionStorage.setItem('auraOwnerToken',value);$('#owner-token').value='';$('#result').textContent='Owner token active for this browser tab session.';refresh()});$('#clear-token').addEventListener('click',()=>{sessionStorage.removeItem('auraOwnerToken');$('#owner-token').value='';$('#result').textContent='Owner token cleared.';refresh()});$('#command-form').addEventListener('submit',e=>{e.preventDefault();const input=$('#command');const text=input.value.trim();if(text)send(text)});const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;const mic=$('#mic');if(SpeechRecognition){mic.addEventListener('click',()=>{const r=new SpeechRecognition();r.lang=navigator.language||'en-IN';r.interimResults=false;r.maxAlternatives=1;r.onresult=e=>{$('#command').value=e.results[0][0].transcript};r.onerror=e=>{$('#result').textContent='Voice input unavailable: '+e.error};r.start()})}else{mic.disabled=true;mic.textContent='Voice unavailable'}if('serviceWorker'in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}))}refresh();setInterval(refresh,30000);"""

_MANIFEST = json.dumps(
    {
        "name": "AURA AI OS Command Center",
        "short_name": "AURA",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#050b14",
        "theme_color": "#07111f",
        "description": "Owner-controlled AURA paper research command center",
    },
    separators=(",", ":"),
)
_SERVICE_WORKER = """const CACHE='aura-command-center-v1';const ASSETS=['/','/styles.css','/app.js','/manifest.webmanifest'];self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));self.addEventListener('fetch',e=>{if(e.request.method!=='GET'||new URL(e.request.url).pathname.startsWith('/api/'))return;e.respondWith(fetch(e.request).then(r=>{const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));return r}).catch(()=>caches.match(e.request)))})"""
