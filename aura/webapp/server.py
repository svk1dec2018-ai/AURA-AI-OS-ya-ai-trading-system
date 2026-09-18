from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from aura.research.autonomy import ResearchHypothesis
from aura.research.blueprint_compiler import (
    EXECUTABLE_CONFIRMATION_PRIMITIVES,
    EXECUTABLE_ENTRY_PRIMITIVES,
    EXECUTABLE_EXIT_PRIMITIVES,
    BlueprintCompilationError,
    compile_blueprint,
)
from aura.research.strategy_factory import AutonomousStrategyFactory
from aura.webapp.catalog import capability_catalog
from aura.webapp.charting import SUPPORTED_TIMEFRAMES, mt5_chart_snapshot
from aura.webapp.operator_assistant import answer_owner_query
from aura.webapp.read_models import (
    decision_feed,
    financial_journal,
    intelligence_feed,
    learning_snapshot,
)
from aura.webapp.research_runner import persist_backtest, run_candidate_backtest
from aura.webapp.security import owner_auth_required, owner_authorized

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
RUNTIME_DIR = ROOT / "runtime" / "aura_web"
DEFAULT_MT5_STATE_DIR = ROOT / "runtime" / "mt5_autonomous_demo"
KILL_LOCK_PATH = RUNTIME_DIR / "kill_switch.json"
LOG_PATH = RUNTIME_DIR / "daemon.log"
ALGO_DIR = RUNTIME_DIR / "algo_candidates"
BACKTEST_DIR = RUNTIME_DIR / "backtests"

VALIDATION_PIPELINE = (
    "compile",
    "causal_backtest",
    "purged_walk_forward",
    "monte_carlo_robustness",
    "sealed_holdout",
    "parameter_stability",
    "regime_validation",
    "paper_demo_forward",
    "human_approval",
)


class AuraWebController:
    """Local owner surface around AURA's governed DEMO/research capabilities.

    The web app never accepts or stores MT5 credentials. The autonomous runtime
    reuses the already logged-in MT5 terminal session and retains its own
    DEMO-only account guard before any broker order can be submitted.

    Algo Studio only creates immutable RESEARCH candidates from allow-listed
    components. It cannot set portfolio risk, enable real money, transfer funds,
    withdraw funds or bypass the validation/promotion lifecycle.
    """

    def __init__(self, state_dir: Path = DEFAULT_MT5_STATE_DIR) -> None:
        self.state_dir = state_dir
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()
        self._log_handle = None
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        ALGO_DIR.mkdir(parents=True, exist_ok=True)
        BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

    def _process_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _tail_log(self, max_chars: int = 12000) -> str:
        try:
            text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-max_chars:]

    def status(self) -> dict[str, Any]:
        status = self._read_json(self.state_dir / "status.json") or {}
        baseline = self._read_json(self.state_dir / "account_baseline.json") or {}
        brain = self._read_json(self.state_dir / "brain" / "status.json") or {}
        kill = self._read_json(KILL_LOCK_PATH)
        with self._lock:
            running = self._process_running()
            exit_code = None if running or self._process is None else self._process.returncode
        return {
            "ok": True,
            "product": "AURA AI OS",
            "ui_version": 2,
            "app_mode": "LOCAL_PWA_DEMO_RESEARCH",
            "release_boundary": "PAPER_DEMO_RESEARCH; UNRESTRICTED_LIVE_MONEY_LOCKED",
            "runtime_running": running,
            "runtime_exit_code": exit_code,
            "app_kill_locked": kill is not None,
            "app_kill_reason": (kill or {}).get("reason"),
            "owner_auth_required": owner_auth_required(),
            "status": status,
            "baseline": {
                "login": baseline.get("login"),
                "server": baseline.get("server"),
                "currency": baseline.get("currency"),
                "starting_balance": baseline.get("starting_balance"),
                "environment": baseline.get("environment"),
            },
            "brain": brain,
            "log_tail": self._tail_log(5000),
            "safety": {
                "demo_only": True,
                "real_money_enabled": False,
                "credentials_accepted_by_web_ui": False,
                "fund_transfers_enabled": False,
                "withdrawals_enabled": False,
                "risk_engine_bypass_allowed": False,
                "ai_direct_broker_authority": False,
            },
        }

    def decisions(self, *, limit: int = 60) -> dict[str, Any]:
        return decision_feed(self.state_dir, limit=limit)

    def journal(self, *, limit: int = 120) -> dict[str, Any]:
        return financial_journal(self.state_dir, limit=limit)

    def learning(self) -> dict[str, Any]:
        return learning_snapshot(self.state_dir)

    def intelligence(self, *, limit: int = 80) -> dict[str, Any]:
        return intelligence_feed(self.state_dir, limit=limit)

    def workspace(self) -> dict[str, Any]:
        decisions = self.decisions(limit=10)
        learning = self.learning()
        intelligence = self.intelligence(limit=12)
        return {
            "ok": True,
            "generated_at": datetime.now(UTC).isoformat(),
            "runtime": self.status(),
            "capabilities": capability_catalog(),
            "decisions": decisions,
            "learning": learning,
            "intelligence": intelligence,
            "algo": {
                "candidate_count": len(self.algo_candidates()),
                "validation_pipeline": list(VALIDATION_PIPELINE),
                "new_candidates_begin_stage": "RESEARCH",
                "auto_live_deploy": False,
            },
        }

    def owner_command(self, text: str) -> dict[str, Any]:
        query = _required_text(text, "text", max_length=2000)
        return answer_owner_query(
            query,
            runtime=self.status(),
            decisions=self.decisions(limit=20),
            learning=self.learning(),
            intelligence=self.intelligence(limit=30),
            candidates=self.algo_candidates(),
            capabilities=capability_catalog(),
        )

    def start(self, *, max_symbols: int = 25, max_batches: int = 100) -> dict[str, Any]:
        if not 1 <= max_symbols <= 1000:
            raise ValueError("max_symbols must be between 1 and 1000")
        if not 1 <= max_batches <= 1_000_000:
            raise ValueError("max_batches must be between 1 and 1000000")
        with self._lock:
            if KILL_LOCK_PATH.exists():
                raise RuntimeError("AURA app kill lock is engaged; reset it before starting")
            if self._process_running():
                return {"ok": True, "already_running": True}
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            self._close_log()
            if LOG_PATH.exists() and LOG_PATH.stat().st_size:
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                LOG_PATH.replace(RUNTIME_DIR / f"daemon-{stamp}.log")
            self._log_handle = LOG_PATH.open("w", encoding="utf-8", buffering=1)
            command = [
                sys.executable,
                "-m",
                "aura.ops.mt5_autonomous_demo",
                "--max-symbols",
                str(max_symbols),
                "--max-batches",
                str(max_batches),
                "--state-dir",
                str(self.state_dir),
            ]
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            self._process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
            return {"ok": True, "started": True, "pid": self._process.pid}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._process_running():
                self._close_log()
                return {"ok": True, "already_stopped": True}
            assert self._process is not None
            if sys.platform == "win32":
                # Windows venv launchers create a child interpreter. Terminating
                # only the launcher can leave a broker worker running unseen.
                subprocess.run(
                    ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                    check=True,
                    capture_output=True,
                    timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            code = self._process.returncode
            self._close_log()
            return {"ok": True, "stopped": True, "exit_code": code}

    def engage_kill_lock(
        self,
        reason: str = "Emergency stop from AURA local PWA",
    ) -> dict[str, Any]:
        result = self.stop()
        payload = {
            "engaged": True,
            "reason": reason,
            "demo_only": True,
            "engaged_at": datetime.now(UTC).isoformat(),
        }
        temp = KILL_LOCK_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(KILL_LOCK_PATH)
        return {"ok": True, "kill_locked": True, "stop_result": result}

    def reset_kill_lock(self) -> dict[str, Any]:
        try:
            KILL_LOCK_PATH.unlink()
        except FileNotFoundError:
            pass
        return {"ok": True, "kill_locked": False}

    def algo_options(self) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "RESEARCH_ONLY",
            "entries": [item.value for item in EXECUTABLE_ENTRY_PRIMITIVES],
            "confirmations": [item.value for item in EXECUTABLE_CONFIRMATION_PRIMITIVES],
            "exits": [item.value for item in EXECUTABLE_EXIT_PRIMITIVES],
            "validation_pipeline": list(VALIDATION_PIPELINE),
            "constraints": {
                "portfolio_risk_parameters_allowed": False,
                "broker_credentials_allowed": False,
                "live_approval_allowed": False,
                "arbitrary_code_allowed": False,
            },
        }

    def build_algo_candidate(self, body: dict[str, Any]) -> dict[str, Any]:
        name = _required_text(body.get("name"), "name", max_length=120)
        thesis = _required_text(body.get("thesis"), "thesis", max_length=1600)
        markets = _string_tuple(body.get("markets"), "markets", max_items=20)
        timeframes = _string_tuple(body.get("timeframes"), "timeframes", max_items=12)
        entries = _enum_tuple(
            body.get("entries"),
            "entries",
            allowed=EXECUTABLE_ENTRY_PRIMITIVES,
            min_items=1,
            max_items=3,
        )
        confirmations = _enum_tuple(
            body.get("confirmations", []),
            "confirmations",
            allowed=EXECUTABLE_CONFIRMATION_PRIMITIVES,
            min_items=0,
            max_items=5,
        )
        exits = _enum_tuple(
            body.get("exits"),
            "exits",
            allowed=EXECUTABLE_EXIT_PRIMITIVES,
            min_items=1,
            max_items=3,
        )

        canonical_request = json.dumps(
            {
                "name": name,
                "thesis": thesis,
                "markets": markets,
                "timeframes": timeframes,
                "entries": [item.value for item in entries],
                "confirmations": [item.value for item in confirmations],
                "exits": [item.value for item in exits],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        request_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        hypothesis = ResearchHypothesis(
            hypothesis_id=f"owner-algo-{request_hash[:12]}",
            thesis=thesis,
            market_scope=markets,
            timeframe_scope=timeframes,
        )

        factory = AutonomousStrategyFactory()
        blueprint = factory.propose_from_components(
            hypothesis,
            entries=entries,
            confirmations=confirmations,
            exits=exits,
            candidate_index=0,
            design_tag=f"owner:{_slug(name)}",
        )
        strategy = factory.register_blueprint(blueprint, candidate_index=0)

        try:
            compiled = compile_blueprint(blueprint)
        except BlueprintCompilationError as exc:
            algorithm = {
                "compilable": False,
                "strategy_id": None,
                "warmup_bars": None,
                "error": str(exc),
            }
        else:
            algorithm = {
                "compilable": True,
                "strategy_id": compiled.strategy_id,
                "warmup_bars": compiled.warmup_bars,
                "error": None,
            }

        candidate = {
            "ok": True,
            "candidate_id": blueprint.blueprint_id,
            "owner_name": name,
            "created_at": datetime.now(UTC).isoformat(),
            "request_hash": request_hash,
            "stage": strategy.stage.value,
            "research_only": True,
            "live_approved": False,
            "algorithm": algorithm,
            "strategy_version": {
                "strategy_id": strategy.strategy_id,
                "version": strategy.version,
                "content_hash": strategy.content_hash,
                "stage": strategy.stage.value,
            },
            "blueprint": blueprint.model_dump(mode="json"),
            "validation": {
                "pipeline": list(VALIDATION_PIPELINE),
                "completed": ["compile"] if algorithm["compilable"] else [],
                "next_required": "causal_backtest" if algorithm["compilable"] else "fix_compile",
                "can_auto_deploy_live": False,
            },
            "safety": {
                "portfolio_risk_owned_by_candidate": False,
                "broker_authority": False,
                "fund_transfer_authority": False,
                "withdrawal_authority": False,
            },
        }
        ALGO_DIR.mkdir(parents=True, exist_ok=True)
        destination = ALGO_DIR / f"{blueprint.content_hash}.json"
        temp = destination.with_suffix(".tmp")
        temp.write_text(
            json.dumps(candidate, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        temp.replace(destination)
        return candidate

    def algo_candidates(self) -> list[dict[str, Any]]:
        ALGO_DIR.mkdir(parents=True, exist_ok=True)
        candidates: list[dict[str, Any]] = []
        for path in sorted(
            ALGO_DIR.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            value = self._read_json(path)
            if value is not None:
                candidates.append(value)
        return candidates[:100]

    def chart(self, *, symbol: str, timeframe: str, bars: int) -> dict[str, Any]:
        return mt5_chart_snapshot(symbol, timeframe, bars=bars)

    def run_backtest(self, body: dict[str, Any]) -> dict[str, Any]:
        candidate_id = _required_text(body.get("candidate_id"), "candidate_id", max_length=160)
        candidate = next(
            (item for item in self.algo_candidates() if item.get("candidate_id") == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("unknown Algo Studio candidate")
        result = run_candidate_backtest(
            candidate,
            symbol=_required_text(body.get("symbol"), "symbol", max_length=120),
            timeframe=_required_text(body.get("timeframe"), "timeframe", max_length=12),
            bars=int(body.get("bars", 1000)),
        )
        artifact = persist_backtest(result, BACKTEST_DIR)
        return {**result, "artifact_file": artifact.name}

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            finally:
                self._log_handle = None

    def shutdown(self) -> None:
        try:
            self.stop()
        except (OSError, subprocess.SubprocessError):
            self._close_log()


def _required_text(value: Any, field: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    normalized = " ".join(value.strip().split())
    if len(normalized) > max_length:
        raise ValueError(f"{field} must be at most {max_length} characters")
    return normalized


def _string_tuple(value: Any, field: str, *, max_items: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    if len(value) > max_items:
        raise ValueError(f"{field} supports at most {max_items} items")
    result: list[str] = []
    for item in value:
        text = _required_text(item, field, max_length=40)
        if text not in result:
            result.append(text)
    if not result:
        raise ValueError(f"{field} must contain at least one value")
    return tuple(result)


def _enum_tuple(
    value: Any,
    field: str,
    *,
    allowed: tuple[Any, ...],
    min_items: int,
    max_items: int,
) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a list")
    if not min_items <= len(value) <= max_items:
        raise ValueError(f"{field} must contain between {min_items} and {max_items} items")
    allowed_values = {item.value: item for item in allowed}
    result: list[Any] = []
    for raw in value:
        key = str(raw)
        if key not in allowed_values:
            raise ValueError(f"unsupported {field} primitive: {key}")
        item = allowed_values[key]
        if item not in result:
            result.append(item)
    if len(result) < min_items:
        raise ValueError(f"{field} must contain at least {min_items} unique items")
    return tuple(result)


def _slug(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in normalized.split("-") if part)[:48] or "strategy"


CONTROLLER = AuraWebController()
atexit.register(CONTROLLER.shutdown)


class AuraRequestHandler(BaseHTTPRequestHandler):
    server_version = "AuraLocalPWA/2.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        )

    def _json(self, payload: dict[str, Any] | list[dict[str, Any]], status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        if length > 64_000:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("request body must be a JSON object")
        return value

    def _require_owner(self) -> bool:
        if owner_authorized(self.headers.get("Authorization")):
            return True
        self._json(
            {
                "ok": False,
                "error": "owner authorization required",
                "owner_auth_required": True,
            },
            HTTPStatus.UNAUTHORIZED,
        )
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            self._json(CONTROLLER.status())
            return
        if path == "/api/workspace":
            self._json(CONTROLLER.workspace())
            return
        if path == "/api/capabilities":
            self._json(capability_catalog())
            return
        if path == "/api/decisions":
            self._json(CONTROLLER.decisions())
            return
        if path == "/api/journal":
            self._json(CONTROLLER.journal())
            return
        if path == "/api/learning":
            self._json(CONTROLLER.learning())
            return
        if path == "/api/intelligence":
            self._json(CONTROLLER.intelligence())
            return
        if path == "/api/security":
            self._json({"ok": True, "owner_auth_required": owner_auth_required()})
            return
        if path == "/api/algo/options":
            self._json(CONTROLLER.algo_options())
            return
        if path == "/api/algo/candidates":
            self._json({"ok": True, "items": CONTROLLER.algo_candidates()})
            return
        if path == "/api/chart":
            try:
                query = parse_qs(parsed.query)
                self._json(
                    CONTROLLER.chart(
                        symbol=(query.get("symbol") or [""])[0],
                        timeframe=(query.get("timeframe") or [""])[0],
                        bars=int((query.get("bars") or ["300"])[0]),
                    )
                )
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/chart/options":
            self._json({"ok": True, "timeframes": list(SUPPORTED_TIMEFRAMES)})
            return
        if path == "/api/health":
            self._json(
                {
                    "ok": True,
                    "service": "aura-local-pwa",
                    "ui_version": 2,
                    "demo_only": True,
                    "real_money_enabled": False,
                    "owner_auth_required": owner_auth_required(),
                }
            )
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/") and not self._require_owner():
            return
        try:
            body = self._body_json()
            if path == "/api/start":
                payload = CONTROLLER.start(
                    max_symbols=int(body.get("max_symbols", 25)),
                    max_batches=int(body.get("max_batches", 100)),
                )
            elif path == "/api/stop":
                payload = CONTROLLER.stop()
            elif path == "/api/kill":
                payload = CONTROLLER.engage_kill_lock(
                    str(body.get("reason") or "Emergency stop from AURA local PWA")
                )
            elif path == "/api/reset-kill":
                payload = CONTROLLER.reset_kill_lock()
            elif path == "/api/algo/build":
                payload = CONTROLLER.build_algo_candidate(body)
            elif path == "/api/backtest/run":
                payload = CONTROLLER.run_backtest(body)
            elif path == "/api/command":
                payload = CONTROLLER.owner_command(str(body.get("text") or ""))
            else:
                self._json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            self._json(payload)
        except (
            TypeError,
            ValueError,
            RuntimeError,
            OSError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
        ) as exc:
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        candidate = (STATIC_DIR / relative).resolve()
        static_root = STATIC_DIR.resolve()
        if static_root not in candidate.parents and candidate != static_root:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.exists() or not candidate.is_file():
            if "." not in Path(relative).name:
                candidate = STATIC_DIR / "index.html"
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
        raw = candidate.read_bytes()
        content_type, _ = mimetypes.guess_type(candidate.name)
        if candidate.suffix == ".webmanifest":
            content_type = "application/manifest+json"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header(
            "Cache-Control",
            (
                "no-cache, must-revalidate"
                if candidate.name == "index.html" or candidate.suffix in {".js", ".css"}
                else "public, max-age=300"
            ),
        )
        self._security_headers()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AURA's local installable owner command-center web app"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Remote binding is disabled in the local-first AURA PWA release")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), AuraRequestHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"AURA AI OS owner command center: {url}")
    print("Protected DEMO/research mode. Keep MT5 open and logged into a DEMO account.")
    if owner_auth_required():
        print("Owner-token protection: enabled (AURA_OWNER_TOKEN)")
    else:
        print("Owner-token protection: optional/off; server remains loopback-only")
    if args.open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        CONTROLLER.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
