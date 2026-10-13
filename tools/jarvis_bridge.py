"""
JARVIS HTTP Bridge — exposes JARVIS's action registry to local agent services.

OpenDots (E:\OpenDots) runs a Node server that calls these endpoints, so a Dot
can ask JARVIS to run its actions. Actions are NOT reimplemented here:
discover_actions() is the same registry main.py offers to the model, and run()
is the same dispatch path tools/ask_jarvis.py proved headless.

Endpoints (all JSON, UTF-8, Bearer-token protected):
    GET  /health   -> {"status":"ok","actions":N,"allowlisted":M}
    GET  /actions  -> {"actions":[{name,description,parameters}]}  (Gemini
                      function-declaration shape, allowlisted entries only)
    POST /run      -> {"ok":true,"result":"..."}  body: {"name":"...","parameters":{...}}

Security model:
    - Binds 127.0.0.1 only; this service never accepts remote connections.
    - Bearer token required: JARVIS_BRIDGE_TOKEN env, or auto-generated on
      first run and stored in config/jarvis_bridge_token.
    - Only allowlisted actions run. The default allowlist is read-only,
      information-shaped actions; override with JARVIS_BRIDGE_ALLOW
      ("*" for everything, or a comma-separated name list).
    - Burmese results are served as UTF-8 with charset declared.

Usage:
    python tools/jarvis_bridge.py            # port 8629
    set JARVIS_BRIDGE_PORT=8629              # optional overrides
    set JARVIS_BRIDGE_ALLOW=open_app,send_message
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

JARVIS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(JARVIS_ROOT))

from core.action_loader import discover_actions  # noqa: E402

DEFAULT_PORT = 8629
TOKEN_FILE = JARVIS_ROOT / "config" / "jarvis_bridge_token"

# Read-only, information-shaped actions. Anything that opens apps, moves
# files, cleans the PC, sends messages or drives the mouse stays out until
# the owner explicitly adds it via JARVIS_BRIDGE_ALLOW.
DEFAULT_ALLOW = frozenset({
    "system_monitor", "weather_report", "news_search", "web_search",
    "daily_briefing", "reminder", "newspaper", "flight_finder",
    "newsroom_status", "newsroom_search", "newsroom_story", "newsroom_digest",
    "reporter_news", "gold_currency", "moi_news", "moi_ministries",
    "moi_council", "moi_documents", "moi_research", "moi_roster",
    "moi_union_offices", "moi_advisory_council", "maps_navigator",
})

# NO global run lock: a slow or hung action (network wait inside a handler)
# must not block every other call — ThreadingHTTPServer already dispatches
# per-request threads. The default allowlist contains only read-only actions;
# owners who widen JARVIS_BRIDGE_ALLOW to desktop-control tools accept the
# shared-state risk that the lock would have papered over.
# END-OF-PART-1B


def resolve_allow(raw: str | None, registry) -> frozenset:
    """Default allowlist, optionally overridden by JARVIS_BRIDGE_ALLOW.

    "*" means every action the registry actually validates and offers —
    including the desktop-control ones, so only the owner sets it on a
    machine (and port) they trust. Names that do not exist in the registry
    are ignored; the loader itself already skips broken files.
    """
    names = raw or os.environ.get("JARVIS_BRIDGE_ALLOW", "")
    if names.strip() == "*":
        return frozenset(registry.names())
    wanted = {n.strip() for n in names.split(",") if n.strip()}
    if wanted:
        return frozenset(wanted & registry.names())
    return frozenset(DEFAULT_ALLOW & registry.names())


def resolve_token() -> str:
    """Bearer token from env, else a generated one persisted under config/.

    The file is created on first run and the token is printed once, so the
    OpenDots .env can copy it. A literal secret in a .py would violate
    review_gate G7; this never hardcodes one.
    """
    env = os.environ.get("JARVIS_BRIDGE_TOKEN", "").strip()
    if env:
        return env
    try:
        existing = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    token = secrets.token_hex(24)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    except OSError:
        # No writable config dir — fall back to an ephemeral token for this
        # process only and say so, rather than disabling auth.
        print("[jarvis_bridge] could not persist token; using an "
              "ephemeral token for this run only", file=sys.stderr)
    return token
class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "JarvisBridge/1.0"
    protocol_version = "HTTP/1.1"

    # populated by serve()
    registry = None        # ActionRegistry
    allow: frozenset = frozenset()
    token: str = ""

    # -- helpers ------------------------------------------------------------

    def _send(self, status: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        expected = f"Bearer {self.token}"
        # compare_digest avoids timing oracles even on a loopback service
        return secrets.compare_digest(header.encode("utf-8"),
                                      expected.encode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:
        # one quiet line per request; Burmese payloads never reach stdout
        sys.stdout.write(f"[jarvis_bridge] {self.command} "
                         f"{self.path.split('?')[0]}\n")

    # -- routes ---------------------------------------------------------------

    def do_GET(self) -> None:
        if not self._authorized():
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        route = self.path.split("?")[0]
        if route == "/health":
            self._send(200, {"status": "ok",
                             "actions": len(self.registry.names()),
                             "allowlisted": len(self.allow)})
            return
        if route == "/actions":
            actions = [
                {"name": d["name"],
                 "description": d.get("description", ""),
                 "parameters": d.get("parameters",
                                     {"type": "OBJECT", "properties": {}})}
                for d in self.registry.get_tool_declarations()
                if d["name"] in self.allow
            ]
            self._send(200, {"actions": actions})
            return
        self._send(404, {"ok": False, "error": "not found"})
    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/run":
            self._send(404, {"ok": False, "error": "not found"})
            return
        if not self._authorized():
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8")
                              or "{}")
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"ok": False, "error": f"bad JSON body: {exc}"})
            return
        name = str(body.get("name") or "")
        parameters = body.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
        if name not in self.allow:
            self._send(403, {"ok": False,
                             "error": f"action '{name}' is not allowlisted"})
            return
        if not self.registry.has(name):
            self._send(404, {"ok": False,
                             "error": f"action '{name}' is not offered"})
            return
        # No global lock — see the comment near DEFAULT_ALLOW. A slow action
        # delays only its own caller, never the whole bridge.
        result = self.registry.run(name, parameters, {})
        self._send(200, {"ok": True, "result": str(result)})

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.end_headers()


def serve() -> None:
    registry = discover_actions(JARVIS_ROOT / "actions")
    allow = resolve_allow(None, registry)
    BridgeHandler.registry = registry
    BridgeHandler.allow = allow
    BridgeHandler.token = resolve_token()

    port = int(os.environ.get("JARVIS_BRIDGE_PORT", DEFAULT_PORT))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), BridgeHandler)
    httpd.daemon_threads = True
    print(f"[jarvis_bridge] {len(registry.names())} actions discovered, "
          f"{len(allow)} allowlisted")
    print(f"[jarvis_bridge] token: {BridgeHandler.token[:4]}..."
          f" (full token in {TOKEN_FILE})")
    print(f"[jarvis_bridge] listening on http://127.0.0.1:{port} "
          f"(Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[jarvis_bridge] shutting down")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()



