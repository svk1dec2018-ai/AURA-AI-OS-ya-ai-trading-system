from __future__ import annotations

import argparse
import atexit
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from aura.webapp import server as base
from aura.webapp.mt5_preflight import mt5_demo_execution_check, mt5_demo_preflight
from aura.webapp.readiness import build_readiness
from aura.webapp.security import owner_auth_required


class AuraWebControllerV3(base.AuraWebController):
    """Canonical owner controller with explicit MT5 connectivity and release readiness."""

    def mt5_preflight(self, *, max_symbols: int = 200, query: str = "") -> dict:
        if query:
            return mt5_demo_preflight(max_symbols=max_symbols, query=query)
        return mt5_demo_preflight(max_symbols=max_symbols)

    def mt5_execution_check(self, *, symbol: str) -> dict:
        return mt5_demo_execution_check(symbol)

    def readiness(self) -> dict:
        preflight = self.mt5_preflight(max_symbols=100)
        return build_readiness(self.status(), preflight)

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
        result = super().start(max_symbols=max_symbols, max_batches=max_batches)
        return {
            **result,
            "mt5_preflight": {
                "demo_verified": True,
                "server": (preflight.get("account") or {}).get("server"),
                "tradable_symbol_count": preflight.get("tradable_symbol_count", 0),
            },
        }


CONTROLLER = AuraWebControllerV3()
base.CONTROLLER = CONTROLLER
atexit.register(CONTROLLER.shutdown)


class AuraRequestHandlerV3(base.AuraRequestHandler):
    server_version = "AuraLocalPWA/3.2"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
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
                payload = CONTROLLER.mt5_execution_check(symbol=symbol)
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
        super().do_GET()

    def _serve_static(self, request_path: str) -> None:
        # Inject product bridges without duplicating the large client shell.
        if request_path in {"", "/", "/index.html"}:
            index_path = base.STATIC_DIR / "index.html"
            text = index_path.read_text(encoding="utf-8")
            marker = '<script src="/app.js" defer></script>'
            scripts: list[str] = []
            if "/mt5-bridge.js" not in text:
                scripts.append('<script src="/mt5-bridge.js?v=3.3" defer></script>')
            if "/readiness-bridge.js" not in text:
                scripts.append('<script src="/readiness-bridge.js?v=3.3" defer></script>')
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
