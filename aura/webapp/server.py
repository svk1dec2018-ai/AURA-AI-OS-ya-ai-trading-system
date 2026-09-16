from __future__ import annotations

import argparse
import atexit
import json
import mimetypes
import os
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
RUNTIME_DIR = ROOT / "runtime" / "aura_web"
DEFAULT_MT5_STATE_DIR = ROOT / "runtime" / "mt5_autonomous_demo"
KILL_LOCK_PATH = RUNTIME_DIR / "kill_switch.json"
LOG_PATH = RUNTIME_DIR / "daemon.log"


class AuraWebController:
    """Small local control surface around the existing AURA MT5 DEMO runtime.

    The web app never accepts or stores MT5 credentials. The autonomous runtime
    reuses the already logged-in MT5 terminal session and retains its own
    DEMO-only account guard before any broker order can be submitted.
    """

    def __init__(self, state_dir: Path = DEFAULT_MT5_STATE_DIR) -> None:
        self.state_dir = state_dir
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()
        self._log_handle = None
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    def _process_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

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
            "app_mode": "LOCAL_PWA_DEMO_ONLY",
            "runtime_running": running,
            "runtime_exit_code": exit_code,
            "app_kill_locked": kill is not None,
            "app_kill_reason": (kill or {}).get("reason"),
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
            },
        }

    def start(self, *, max_symbols: int = 10, max_batches: int = 100) -> dict[str, Any]:
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
            self._log_handle = LOG_PATH.open("a", encoding="utf-8", buffering=1)
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
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            code = self._process.returncode
            self._close_log()
            return {"ok": True, "stopped": True, "exit_code": code}

    def engage_kill_lock(self, reason: str = "Emergency stop from AURA local PWA") -> dict[str, Any]:
        result = self.stop()
        payload = {"engaged": True, "reason": reason, "demo_only": True}
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

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            finally:
                self._log_handle = None

    def shutdown(self) -> None:
        try:
            self.stop()
        except Exception:
            self._close_log()


CONTROLLER = AuraWebController()
atexit.register(CONTROLLER.shutdown)


class AuraRequestHandler(BaseHTTPRequestHandler):
    server_version = "AuraLocalPWA/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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
            raise ValueError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json(CONTROLLER.status())
            return
        if path == "/api/health":
            self._json({"ok": True, "service": "aura-local-pwa", "demo_only": True})
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._body_json()
            if path == "/api/start":
                payload = CONTROLLER.start(
                    max_symbols=int(body.get("max_symbols", 10)),
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
            else:
                self._json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            self._json(payload)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
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
        self.send_header("Cache-Control", "no-cache" if candidate.name == "index.html" else "public, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AURA's local installable demo-only web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Remote binding is disabled in the first demo-only PWA release")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), AuraRequestHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"AURA local PWA: {url}")
    print("DEMO ONLY. Keep MT5 open and logged into a DEMO account.")
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
