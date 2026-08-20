from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlparse

from aura.interface.command_center import AssistantIntent, CommandRouter
from aura.interface.operator_read_model import OperatorReadModel, ReadDomain
from aura.interface.web_command_center import CommandCenterConfig, CommandCenterService


class CommandCenterV2Service(CommandCenterService):
    """Owner-facing observation/research cockpit over freshness-gated read models.

    V2 deliberately remains a read/research surface: it contains no broker order
    adapter and still rejects PAPER_CONTROL and LIVE_CONTROL before execution.
    """

    def __init__(
        self,
        config: CommandCenterConfig | None = None,
        *,
        router: CommandRouter | None = None,
        read_model: OperatorReadModel | None = None,
    ) -> None:
        super().__init__(config, router=router)
        self.read_model = read_model or OperatorReadModel()

    def status(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        base = super().status()
        overview = self.read_model.overview(as_of=now)
        available = sorted(
            domain
            for domain, view in overview.items()
            if bool(view["available"])
        )
        stale = sorted(
            domain
            for domain, view in overview.items()
            if bool(view["stale"])
        )
        base.update(
            {
                "ui_version": 2,
                "available_read_domains": available,
                "stale_read_domains": stale,
                "market_data_source": _view_source(overview[ReadDomain.OPPORTUNITIES.value]),
                "risk_source": _view_source(overview[ReadDomain.RISK.value]),
                "portfolio_source": _view_source(overview[ReadDomain.PORTFOLIO.value]),
            }
        )
        return base

    def handle_command(
        self,
        text: str,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        command = self.router.parse(text)
        if command.intent in {
            AssistantIntent.LIVE_CONTROL,
            AssistantIntent.PAPER_CONTROL,
            AssistantIntent.RESEARCH_REQUEST,
        }:
            return super().handle_command(text, idempotency_key=idempotency_key)
        if command.intent is AssistantIntent.STATUS:
            return HTTPStatus.OK, {
                "accepted": True,
                "command_id": command.command_id,
                "intent": command.intent.value,
                "summary": "AURA Command Center v2 status",
                "payload": self.status(),
            }
        if command.intent is AssistantIntent.MARKET_SCAN:
            return self._read_command(command.command_id, command.intent, ReadDomain.OPPORTUNITIES)
        if command.intent is AssistantIntent.RISK_STATUS:
            return self._read_command(command.command_id, command.intent, ReadDomain.RISK)
        if command.intent is AssistantIntent.POSITIONS:
            return self._read_command(command.command_id, command.intent, ReadDomain.PORTFOLIO)
        if command.intent is AssistantIntent.EXPLAIN:
            return self._explain(command.command_id, command.parameters.get("symbol"))
        return super().handle_command(text, idempotency_key=idempotency_key)

    def _read_command(
        self,
        command_id: str,
        intent: AssistantIntent,
        domain: ReadDomain,
    ) -> tuple[int, dict[str, Any]]:
        view = self.read_model.get(domain)
        if not view.available or view.payload is None:
            return HTTPStatus.SERVICE_UNAVAILABLE, {
                "accepted": False,
                "command_id": command_id,
                "intent": intent.value,
                "summary": f"fresh governed {domain.value} source is unavailable",
                "payload": view.to_json_dict(),
            }
        return HTTPStatus.OK, {
            "accepted": True,
            "command_id": command_id,
            "intent": intent.value,
            "summary": f"fresh governed {domain.value} snapshot",
            "payload": view.to_json_dict(),
        }

    def _explain(
        self,
        command_id: str,
        symbol: str | None,
    ) -> tuple[int, dict[str, Any]]:
        view = self.read_model.get(ReadDomain.OPPORTUNITIES)
        if not view.available or view.payload is None:
            return HTTPStatus.SERVICE_UNAVAILABLE, {
                "accepted": False,
                "command_id": command_id,
                "intent": AssistantIntent.EXPLAIN.value,
                "summary": "fresh opportunity evidence is unavailable",
                "payload": view.to_json_dict(),
            }
        items = view.payload.get("items")
        if not isinstance(items, list):
            items = []
        selected: dict[str, Any] | None = None
        if symbol:
            normalized = symbol.upper()
            selected = next(
                (
                    item
                    for item in items
                    if isinstance(item, dict) and str(item.get("symbol", "")).upper() == normalized
                ),
                None,
            )
        elif items and isinstance(items[0], dict):
            selected = items[0]
        if selected is None:
            return HTTPStatus.NOT_FOUND, {
                "accepted": False,
                "command_id": command_id,
                "intent": AssistantIntent.EXPLAIN.value,
                "summary": "no matching governed opportunity is available to explain",
                "payload": {"symbol": symbol, "source": view.source},
            }
        return HTTPStatus.OK, {
            "accepted": True,
            "command_id": command_id,
            "intent": AssistantIntent.EXPLAIN.value,
            "summary": "deterministic CEO opportunity explanation",
            "payload": {
                "source": view.source,
                "observed_at": None if view.observed_at is None else view.observed_at.isoformat(),
                "opportunity": selected,
            },
        }

    def make_server(self) -> ThreadingHTTPServer:
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AURACommandCenter/2.0"

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

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path.startswith("/api/") and not self._authorized():
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                assets = {
                    "/": (_INDEX_HTML, "text/html; charset=utf-8"),
                    "/v2-app.js": (_APP_JS, "text/javascript; charset=utf-8"),
                    "/v2-styles.css": (_STYLES_CSS, "text/css; charset=utf-8"),
                    "/manifest.webmanifest": (
                        _MANIFEST,
                        "application/manifest+json; charset=utf-8",
                    ),
                    "/v2-sw.js": (_SERVICE_WORKER, "text/javascript; charset=utf-8"),
                }
                if path in assets:
                    text, content_type = assets[path]
                    self._write(HTTPStatus.OK, text.encode("utf-8"), content_type)
                    return
                if path in {"/api/health", "/api/status"}:
                    self._json(HTTPStatus.OK, service.status())
                    return
                if path == "/api/overview":
                    self._json(HTTPStatus.OK, service.read_model.overview())
                    return
                domain = _API_DOMAIN_PATHS.get(path)
                if domain is not None:
                    view = service.read_model.get(domain)
                    status = HTTPStatus.OK if view.available else HTTPStatus.SERVICE_UNAVAILABLE
                    self._json(status, view.to_json_dict())
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
                    idempotency_key=key,
                )
                self._json(status, result)

        return ThreadingHTTPServer((self.config.host, self.config.port), Handler)


_API_DOMAIN_PATHS = {
    "/api/opportunities": ReadDomain.OPPORTUNITIES,
    "/api/portfolio": ReadDomain.PORTFOLIO,
    "/api/risk": ReadDomain.RISK,
    "/api/agents": ReadDomain.AGENTS,
    "/api/data": ReadDomain.DATA,
    "/api/brokers": ReadDomain.BROKERS,
    "/api/system": ReadDomain.SYSTEM,
    "/api/research": ReadDomain.RESEARCH,
}


def _view_source(view: Mapping[str, Any]) -> str:
    return str(view["source"]) if view.get("available") and view.get("source") else "not_attached"


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#07111f">
<title>AURA Command Center v2</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="stylesheet" href="/v2-styles.css">
</head>
<body>
<main>
<header>
<div><p class="eyebrow">AURA AI OS · OWNER COCKPIT</p><h1>Command Center <span>v2</span></h1>
<p class="sub">Governed market intelligence, risk visibility and research. No broker order controls.</p></div>
<div class="head-status"><span id="health" class="pill">connecting</span><small id="updated">—</small></div>
</header>
<section class="status-grid" id="domain-grid"></section>
<section class="panel radar-panel">
<div class="panel-head"><div><p class="eyebrow">MARKET INTELLIGENCE</p><h2>Opportunity Radar</h2></div><span id="radar-count" class="pill">0 actionable</span></div>
<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Market</th><th>Intent</th><th>Score</th><th>CEO</th><th>Alignment</th><th>Risk</th><th>As of</th></tr></thead><tbody id="radar-body"><tr><td colspan="8" class="empty">Fresh governed radar not attached.</td></tr></tbody></table></div>
</section>
<section class="split">
<article class="panel"><div class="panel-head"><div><p class="eyebrow">RISK AUTHORITY</p><h2>Independent Risk</h2></div></div><pre id="risk-view">Unavailable.</pre></article>
<article class="panel"><div class="panel-head"><div><p class="eyebrow">PORTFOLIO</p><h2>Positions & P&amp;L</h2></div></div><pre id="portfolio-view">Unavailable.</pre></article>
</section>
<section class="panel console">
<div class="panel-head"><div><p class="eyebrow">VOICE / TEXT</p><h2>Talk to AURA</h2><p>Try “scan markets”, “risk status”, “portfolio”, or “explain for BTC/USD”.</p></div><button id="mic" type="button">🎙 Voice</button></div>
<form id="command-form"><input id="command" maxlength="4000" autocomplete="off" placeholder="Hi AURA, scan markets…"><button type="submit">Send</button></form>
<pre id="result" aria-live="polite">Ready. Trading controls remain disabled.</pre>
</section>
<footer>Freshness-gated observation + governed research · stale payloads hidden · no live/paper execution controls</footer>
</main>
<script src="/v2-app.js" defer></script>
</body>
</html>"""

_STYLES_CSS = """:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#e7eef8;background:#050b14;color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 12% 0,#123251 0,transparent 34%),radial-gradient(circle at 90% 12%,#10233b 0,transparent 30%),#050b14}main{width:min(1220px,calc(100% - 28px));margin:auto;padding:28px 0 48px}header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:18px}.eyebrow{letter-spacing:.17em;text-transform:uppercase;color:#7dd3fc;font-size:.7rem;margin:0 0 6px}h1{font-size:clamp(2rem,6vw,4.1rem);line-height:.95;margin:0}h1 span{font-size:.32em;color:#7dd3fc;vertical-align:top}h2{margin:0}.sub,.panel p,footer,small{color:#92a6bd}.head-status{display:flex;align-items:flex-end;flex-direction:column;gap:8px}.pill{border:1px solid #2c4d6d;border-radius:999px;padding:7px 11px;color:#9ed9ff}.status-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:12px}.status-card,.panel{background:#0a1522d9;border:1px solid #1e344b;border-radius:18px;box-shadow:0 16px 44px #0007}.status-card{padding:14px;min-height:92px}.status-card span{display:block;color:#8da2ba;font-size:.78rem}.status-card strong{display:block;margin-top:10px;font-size:1rem}.status-card em{display:block;margin-top:5px;font-style:normal;font-size:.72rem;color:#748ba4}.ok{color:#a7f3d0!important}.warn{color:#fde68a!important}.bad{color:#fca5a5!important}.panel{padding:18px;margin-bottom:12px}.panel-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.table-wrap{overflow:auto;margin-top:14px}table{width:100%;border-collapse:collapse;min-width:800px}th,td{text-align:left;padding:11px;border-bottom:1px solid #172b3f;font-size:.84rem}th{color:#86a0bb;font-weight:600}.empty{text-align:center;color:#71869c;padding:28px}.intent-LONG{color:#a7f3d0}.intent-SHORT{color:#fca5a5}.intent-FLAT{color:#fde68a}.split{display:grid;grid-template-columns:1fr 1fr;gap:12px}.split .panel{margin:0}pre{white-space:pre-wrap;word-break:break-word;background:#050b14;border-radius:12px;padding:13px;min-height:130px;max-height:330px;overflow:auto;color:#c7d9ed}form{display:flex;gap:10px;margin-top:16px}input,button{font:inherit;border-radius:12px;border:1px solid #2b4a68}input{flex:1;min-width:0;background:#06101d;color:#eef6ff;padding:14px}button{cursor:pointer;background:#11304c;color:#eaf6ff;padding:12px 16px}button:hover{background:#184264}footer{text-align:center;margin-top:20px;font-size:.82rem}@media(max-width:980px){.status-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:720px){main{width:min(100% - 18px,1220px);padding-top:18px}header{flex-direction:column}.head-status{align-items:flex-start}.status-grid{grid-template-columns:repeat(2,1fr)}.split{grid-template-columns:1fr}form{flex-direction:column}.panel-head{align-items:flex-start}}"""

_APP_JS = """const $=s=>document.querySelector(s);const domains=['opportunities','risk','portfolio','agents','data','brokers'];function esc(v){return String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]))}function domainCard(name,v){const state=v.available?'fresh':(v.stale?'stale':'unavailable');const cls=v.available?'ok':(v.stale?'warn':'bad');const age=v.age_seconds==null?'—':Math.round(v.age_seconds)+'s';return `<article class="status-card"><span>${esc(name)}</span><strong class="${cls}">${state}</strong><em>${esc(v.source||'not attached')} · ${age}</em></article>`}async function get(path){const r=await fetch(path,{cache:'no-store'});const p=await r.json();return {ok:r.ok,status:r.status,p}}function renderRadar(view){const body=$('#radar-body');if(!view.available||!view.payload){body.innerHTML='<tr><td colspan="8" class="empty">Fresh governed radar unavailable.</td></tr>';$('#radar-count').textContent='0 actionable';return}const p=view.payload;const items=Array.isArray(p.items)?p.items:[];$('#radar-count').textContent=(p.actionable_count||0)+' actionable';if(!items.length){body.innerHTML='<tr><td colspan="8" class="empty">No ranked candidates in current snapshot.</td></tr>';return}body.innerHTML=items.slice(0,30).map(x=>`<tr><td>${esc(x.rank)}</td><td><strong>${esc(x.symbol)}</strong><br><small>${esc(x.venue)} · ${esc(x.timeframe)}</small></td><td class="intent-${esc(x.intent)}">${esc(x.intent)}</td><td>${esc(x.score)}</td><td>${esc(Math.round((x.ceo_confidence||0)*100))}%</td><td>${esc(Math.round((x.technical_alignment||0)*100))}%</td><td>${x.risk_flags?.length?esc(x.risk_flags.join(', ')):'—'}</td><td>${esc(x.as_of||'—')}</td></tr>`).join('')}async function refresh(){try{const [status,overview]=await Promise.all([get('/api/status'),get('/api/overview')]);if(!status.ok)throw new Error('status '+status.status);$('#health').textContent='online · '+status.p.execution_mode;$('#updated').textContent='updated '+new Date().toLocaleTimeString();const o=overview.p;$('#domain-grid').innerHTML=domains.map(d=>domainCard(d,o[d]||{})).join('');renderRadar(o.opportunities||{});$('#risk-view').textContent=o.risk?.available?JSON.stringify(o.risk.payload,null,2):JSON.stringify(o.risk||{},null,2);$('#portfolio-view').textContent=o.portfolio?.available?JSON.stringify(o.portfolio.payload,null,2):JSON.stringify(o.portfolio||{},null,2)}catch(e){$('#health').textContent='offline';$('#result').textContent='Refresh error: '+e.message}}async function send(text){$('#result').textContent='Working…';const key=crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random();try{const r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify({text})});const p=await r.json();$('#result').textContent=JSON.stringify(p,null,2);await refresh()}catch(e){$('#result').textContent='Command error: '+e.message}}$('#command-form').addEventListener('submit',e=>{e.preventDefault();const input=$('#command');const text=input.value.trim();if(text)send(text)});const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;const mic=$('#mic');if(SpeechRecognition){mic.addEventListener('click',()=>{const r=new SpeechRecognition();r.lang=navigator.language||'en-IN';r.interimResults=false;r.maxAlternatives=1;r.onresult=e=>{$('#command').value=e.results[0][0].transcript};r.onerror=e=>{$('#result').textContent='Voice input unavailable: '+e.error};r.start()})}else{mic.disabled=true;mic.textContent='Voice unavailable'}if('serviceWorker'in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('/v2-sw.js').catch(()=>{}))}refresh();setInterval(refresh,15000);"""

_MANIFEST = json.dumps(
    {
        "name": "AURA AI OS Command Center v2",
        "short_name": "AURA",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#050b14",
        "theme_color": "#07111f",
        "description": "Owner-controlled AURA market intelligence and research cockpit",
    },
    separators=(",", ":"),
)

_SERVICE_WORKER = """const CACHE='aura-command-center-v2';const ASSETS=['/','/v2-styles.css','/v2-app.js','/manifest.webmanifest'];self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));self.addEventListener('fetch',e=>{if(e.request.method!=='GET'||new URL(e.request.url).pathname.startsWith('/api/'))return;e.respondWith(fetch(e.request).then(r=>{const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));return r}).catch(()=>caches.match(e.request)))})"""
