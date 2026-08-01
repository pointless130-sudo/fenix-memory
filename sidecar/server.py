"""Local HTTP sidecar — the same three operations for non-MCP runtimes.

Localhost only, stdlib only. The HTTP layer is a thin shell over
sdk.api.dispatch; `handle_request` is the pure request handler the test
suite exercises directly (the suite runs under a no-network guard, so
socket binding is covered by an opt-in smoke test instead).

  POST /commit   POST /recall   POST /prove     body: JSON params
  GET  /status
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdk.api import DispatchError, dispatch  # noqa: E402

ROUTES = {"commit", "recall", "prove", "status"}


def handle_request(method: str, path: str, body: bytes, memory_dir: str) -> tuple[int, dict]:
    """Pure request handler: (HTTP status, JSON-serializable response)."""
    op = path.strip("/")
    if op not in ROUTES:
        return 404, {"error": f"unknown path /{op}; valid: {sorted(ROUTES)}"}
    if op == "status":
        if method != "GET":
            return 405, {"error": "status is GET"}
        params: dict = {}
    else:
        if method != "POST":
            return 405, {"error": f"{op} is POST"}
        try:
            params = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError as exc:
            return 400, {"error": f"invalid JSON body: {exc}"}
        if not isinstance(params, dict):
            return 400, {"error": "body must be a JSON object"}
    params["memory_dir"] = memory_dir  # the sidecar owns the memory location
    try:
        return 200, dispatch(op, params)
    except DispatchError as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:
        return 500, {"error": f"internal error: {exc}"}


class SidecarHandler(BaseHTTPRequestHandler):
    memory_dir = ""  # injected by main()

    def _respond(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        status, payload = handle_request(method, self.path, body, self.memory_dir)
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._respond("GET")

    def do_POST(self):  # noqa: N802
        self._respond("POST")

    def log_message(self, *args):  # quiet by default
        pass


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="fenix-block HTTP sidecar (localhost)")
    ap.add_argument("--memory-dir", required=True)
    ap.add_argument("--port", type=int, default=7691)
    args = ap.parse_args(argv)
    handler = type("Handler", (SidecarHandler,), {"memory_dir": args.memory_dir})
    server = HTTPServer(("127.0.0.1", args.port), handler)
    print(f"fenix-block sidecar on http://127.0.0.1:{args.port} (memory: {args.memory_dir})")
    server.serve_forever()
    return 0
