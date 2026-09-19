from __future__ import annotations

import argparse
import atexit
import json
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from aura.domain.models import Side
from aura.fleet.status import distributed_fleet_status
from aura.fleet.streaming import DEFAULT_SSE_STREAMS, RedisFleetSSE
from aura.webapp import server as base
from aura.webapp.charting import mt5_live_quote
from aura.webapp.mt5_preflight import (
    mt5_demo_execution_check,
    mt5_demo_preflight,
    mt5_live_terminal_snapshot,
)
from aura.webapp.readiness import build_readiness
from aura.webapp.security import owner_auth_required


class AuraWebControllerV3(base.AuraWebController):
    """Canonical owner controller with explicit MT5 connectivity and release readiness."""

    def mt5_preflight(self, *, max_symbols: int = 200, query: str = "") -> dict:
        if query:
            return mt5_demo_preflight(max_symbols=max_symbols, query=query)
        return mt5_demo_preflight(max_symbols=max_symbols)

    def mt5_execution_check(self, *, symbol: str, side: Side = Side.BUY) -> dict:
        preflight = self.mt5_preflight(max_symbols=1, query=symbol)
        if preflight.get("market_clock_ok") is not True:
            clock = preflight.get("market_clock") or {}
            return {
                "ok": False,
                "execution_ready": False,
                "demo_verified": bool(preflight.get("demo_verified")),
                "symbol": symbol,
                "side": side.value,
                "error": (
                    "protected preview blocked by market clock: "
                    + str(clock.get("error") or "clock evidence unavailable")
                ),
                "market_clock": clock,
                "order_check_attempted": False,
                "order_submission_attempted": False,
                "real_money_enabled": False,
            }
        return mt5_demo_execution_check(symbol, side=side)

    def readiness(self) -> dict:
        preflight = self.mt5_preflight(max_symbols=100)
        return build_readiness(self.status(), preflight)

    def live_quote(self, *, symbol: str) -> dict:
        return mt5_live_quote(symbol)

    def live_terminal(self, *, symbols: tuple[str, ...] | None = None) -> dict:
        return mt5_live_terminal_snapshot(symbols)

    def diagnostics(self) -> dict:
        runtime = self.status()
        try:
            preflight = self.mt5_preflight(max_symbols=25)
        except (TypeError, ValueError, RuntimeError, OSError) as exc:
            preflight = {
                "ok": False,
                "demo_verified": False,
                "connected": False,
                "error": str(exc),
                "tradable_symbol_count": 0,
            }
        return {
            "ok": True,
            "backend": {
                "ok": True,
                "service": "aura-web-v3",
                "runtime_running": bool(runtime.get("runtime_running")),
                "runtime_exit_code": runtime.get("runtime_exit_code"),
                "recovery_error": runtime.get("recovery_error"),
            },
            "mt5": preflight,
            "real_money_enabled": False,
        }

    def start(self, *, max_symbols: int = 25, max_batches: int = 100) -> dict:
        preflight = self.mt5_preflight(max_symbols=max(50, max_symbols))
        if not preflight.get("ok"):
            raise RuntimeError(
                "MT5 DEMO preflight failed: "
                + str(preflight.get("error") or "terminal/account is not ready")
            )
        if int(preflight.get("tradable_symbol_count", 0)) <= 0:
            raise RuntimeError("MT5 DEMO preflight found no tradable symbols")
        if preflight.get("market_clock_ok") is not True:
            clock = preflight.get("market_clock") or {}
            raise RuntimeError(
                "MT5 DEMO start blocked: broker market timestamps are not safe for "
                f"point-in-time decisions ({clock.get('error') or 'clock evidence unavailable'}; "
                f"future_skew_seconds={clock.get('future_skew_seconds')})"
            )

        # Make Start AURA self-contained: use the active clock contract as the
        # broker-side execution probe, then require a successful NO-SEND
        # order_check before the autonomous DEMO child process can start.
        clock = preflight.get("market_clock") or {}
        probe_symbol = str(clock.get("symbol") or "").strip()
        if not probe_symbol:
            probe_symbol = next(
                (
                    str(item.get("symbol") or "").strip()
                    for item in preflight.get("symbols", [])
                    if str(item.get("symbol") or "").strip()
                ),
                "",
            )
        if not probe_symbol:
            raise RuntimeError("MT5 DEMO start blocked: no symbol available for execution check")
        execution = mt5_demo_execution_check(probe_symbol, side=Side.BUY)
        if execution.get("execution_ready") is not True:
            raise RuntimeError(
                "MT5 DEMO execution readiness failed: "
                + str(execution.get("error") or "broker order_check did not approve the protected probe")
            )

        result = super().start(max_symbols=max_symbols, max_batches=max_batches)
        return {
            **result,
            "mt5_preflight": {
                "demo_verified": True,
                "server": (preflight.get("account") or {}).get("server"),
                "tradable_symbol_count": preflight.get("tradable_symbol_count", 0),
            },
            "mt5_execution_check": {
                "execution_ready": True,
                "requested_symbol": execution.get("requested_symbol", probe_symbol),
                "symbol": execution.get("symbol", probe_symbol),
                "order_check_attempted": bool(execution.get("order_check_attempted")),
                "order_submission_attempted": False,
                "real_money_enabled": False,
            },
        }


CONTROLLER = AuraWebControllerV3()
base.CONTROLLER = CONTROLLER
atexit.register(CONTROLLER.shutdown)


class AuraRequestHandlerV3(base.AuraRequestHandler):
    server_version = "AuraLocalPWA/3.4"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/diagnostics":
            self._json(CONTROLLER.diagnostics())
            return
        if parsed.path == "/api/fleet/status":
            self._json(distributed_fleet_status())
            return
        if parsed.path == "/api/fleet/events":
            query = parse_qs(parsed.query)
            raw_streams = str((query.get("streams") or [""])[0])
            streams = tuple(
                item.strip()
                for item in raw_streams.split(",")
                if item.strip()
            ) or DEFAULT_SSE_STREAMS
            self._stream_fleet_events(streams)
            return
        if parsed.path == "/api/mt5/live":
            query = parse_qs(parsed.query)
            raw_symbols = str((query.get("symbols") or [""])[0])
            symbols = tuple(
                item.strip()
                for item in raw_symbols.split(",")
                if item.strip()
            ) or None
            try:
                self._json(CONTROLLER.live_terminal(symbols=symbols))
            except (TypeError, ValueError, RuntimeError, OSError, KeyError, AttributeError) as exc:
                self._json({"ok": False, "error": str(exc)}, 503)
            return
        if parsed.path == "/api/workspace":
            try:
                self._json(CONTROLLER.workspace())
            except (TypeError, ValueError, RuntimeError, OSError, KeyError, AttributeError) as exc:
                self._json({
                    "ok": False,
                    "error": "workspace read failed: " + str(exc),
                    "runtime": CONTROLLER.status(),
                }, 503)
            return
        if parsed.path == "/api/algo/candidates":
            try:
                self._json({"ok": True, "items": CONTROLLER.algo_candidates()})
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                self._json({"ok": False, "error": "candidate catalog failed: " + str(exc)}, 503)
            return
        if parsed.path == "/api/mt5/preflight":
            query = parse_qs(parsed.query)
            try:
                max_symbols = int((query.get("max_symbols") or ["200"])[0])
                search = str((query.get("q") or [""])[0])
                self._json(CONTROLLER.mt5_preflight(max_symbols=max_symbols, query=search))
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/mt5/execution-check":
            query = parse_qs(parsed.query)
            try:
                symbol = str((query.get("symbol") or ["XAUUSD"])[0])
                side = Side(str((query.get("side") or [Side.BUY.value])[0]).upper())
                payload = CONTROLLER.mt5_execution_check(symbol=symbol, side=side)
                self._json(payload, 200 if payload.get("ok") else 400)
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/readiness":
            try:
                self._json(CONTROLLER.readiness())
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/mt5/quote":
            query = parse_qs(parsed.query)
            try:
                symbol = str((query.get("symbol") or ["XAUUSD"])[0])
                self._json(CONTROLLER.live_quote(symbol=symbol))
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            return
        super().do_GET()

    def _stream_fleet_events(self, streams: tuple[str, ...]) -> None:
        import os

        reader = RedisFleetSSE(
            os.environ.get("AURA_REDIS_URL", "redis://127.0.0.1:6379/0")
        )
        try:
            try:
                redis_ready = reader.ping()
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                self._json({"ok": False, "error": "Fleet Redis unavailable: " + str(exc)}, 503)
                return
            if not redis_ready:
                self._json({"ok": False, "error": "Redis ping failed"}, 503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "keep-alive")
            self._security_headers()
            self.end_headers()
            for chunk in reader.iter_sse(streams):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            try:
                self.wfile.write(
                    ("data: " + json.dumps({"error": str(exc)}) + "\n\n").encode("utf-8")
                )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        finally:
            reader.close()

    def _serve_static(self, request_path: str) -> None:
        # Inject product bridges without duplicating the large client shell.
        if request_path in {"", "/", "/index.html"}:
            index_path = base.STATIC_DIR / "index.html"
            text = index_path.read_text(encoding="utf-8")
            marker = '<script src="/app.js" defer></script>'
            scripts: list[str] = []
            if "/mt5-bridge.js" not in text:
                scripts.append('<script src="/mt5-bridge.js?v=3.4" defer></script>')
            if "/readiness-bridge.js" not in text:
                scripts.append('<script src="/readiness-bridge.js?v=3.4" defer></script>')
            if scripts:
                text = text.replace(marker, "\n".join(scripts + [marker]))
            raw = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self._security_headers()
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        super()._serve_static(request_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AURA owner command center with MT5 DEMO preflight"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    parser.add_argument(
        "--auto-start-demo",
        action="store_true",
        help="Automatically start protected MT5 DEMO runtime after PWA startup.",
    )
    parser.add_argument("--auto-start-symbols", type=int, default=25)
    parser.add_argument("--auto-start-batches", type=int, default=0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Remote binding is disabled in the local-first AURA PWA release")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), AuraRequestHandlerV3)
    url = f"http://127.0.0.1:{args.port}"
    print(f"AURA AI OS owner command center: {url}")
    print("Release: AURA AI OS 0.2 / protected MT5 DEMO production candidate")
    print("MT5 DEMO preflight is enabled. Keep MT5 open and logged into a DEMO account.")
    if owner_auth_required():
        print("Owner-token protection: enabled (AURA_OWNER_TOKEN)")
    else:
        print("Owner-token protection: optional/off; server remains loopback-only")

    def auto_start_demo() -> None:
        try:
            payload = CONTROLLER.start(
                max_symbols=args.auto_start_symbols,
                max_batches=args.auto_start_batches,
            )
            state = "already active" if payload.get("already_running") else "started"
            probe = payload.get("mt5_execution_check") or {}
            print(
                "AURA protected DEMO auto-start "
                f"{state}; broker probe={probe.get('symbol', 'verified')} "
                "(NO-SEND readiness check passed)."
            )
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            # Fail closed. The web app remains available so the owner can inspect
            # MT5/readiness and retry after fixing the external condition.
            print(f"AURA protected DEMO auto-start blocked: {exc}")

    if args.open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    if args.auto_start_demo:
        CONTROLLER._desired_running = args.auto_start_batches == 0
        CONTROLLER._restart_options = {
            "max_symbols": args.auto_start_symbols,
            "max_batches": args.auto_start_batches,
        }
        threading.Timer(1.2, auto_start_demo).start()
    recovery_stop = threading.Event()

    def recover_worker() -> None:
        while not recovery_stop.wait(60):
            CONTROLLER.recover_continuous_runtime()

    threading.Thread(target=recover_worker, name="aura-recovery", daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        recovery_stop.set()
        server.server_close()
        CONTROLLER.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
