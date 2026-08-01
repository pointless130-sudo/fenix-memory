from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdk.api import DispatchError, dispatch  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"

_SHARD_SCHEMA = {
    "type": "object",
    "required": ["type", "key", "body", "created_at"],
    "properties": {
        "type": {"type": "string", "enum": ["facts", "decisions", "gotchas", "artifacts"]},
        "key": {"type": "string"},
        "body": {"type": "object"},
        "created_at": {"type": "string", "description": "ISO-8601 UTC"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}

TOOLS = [
    {
        "name": "memory_commit",
        "description": "Commit shards to the agent memory; returns the new root CID. Append-only.",
        "inputSchema": {
            "type": "object",
            "required": ["shards"],
            "properties": {
                "shards": {"type": "array", "items": _SHARD_SCHEMA},
                "committed_at": {"type": "string"},
            },
        },
    },
    {
        "name": "memory_recall",
        "description": ("Resolve only matching shards via the manifest — never replays history. "
                        "Query fields (ANDed): type, key, prefix, contains."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "object"},
                "root": {"type": "string", "description": "root CID; defaults to head"},
            },
        },
    },
    {
        "name": "memory_prove",
        "description": "Merkle inclusion proof that a shard is part of a committed root.",
        "inputSchema": {
            "type": "object",
            "required": ["claim"],
            "properties": {"claim": {"type": "object"}},
        },
    },
]

_TOOL_TO_OP = {"memory_commit": "commit", "memory_recall": "recall", "memory_prove": "prove"}


class MCPServer:
    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir

    # ---- one JSON-RPC message in, one response dict out (None for notifications) ----

    def handle(self, msg: dict) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
            return self._error(msg.get("id") if isinstance(msg, dict) else None,
                               -32600, "invalid request")
        method = msg["method"]
        msg_id = msg.get("id")
        is_notification = "id" not in msg
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fenix-block", "version": "0.1.0"},
                }
            elif method == "ping":
                result = {}
            elif method.startswith("notifications/"):
                return None
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._call_tool(msg.get("params") or {})
            else:
                return None if is_notification else self._error(msg_id, -32601, f"method not found: {method}")
        except DispatchError as exc:
            # Tool-level failure: MCP reports it as a tool result with isError.
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except Exception as exc:  # never crash the server on a bad message
            return None if is_notification else self._error(msg_id, -32603, f"internal error: {exc}")
        return None if is_notification else {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        if name not in _TOOL_TO_OP:
            raise DispatchError(f"unknown tool {name!r}")
        args = dict(params.get("arguments") or {})
        args["memory_dir"] = self.memory_dir  # the server owns the memory location
        result = dispatch(_TOOL_TO_OP[name], args)
        return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False}

    @staticmethod
    def _error(msg_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    # ---- stdio transport: newline-delimited JSON-RPC ----

    def serve_stdio(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                resp = self._error(None, -32700, "parse error")
            else:
                resp = self.handle(msg)
            if resp is not None:
                stdout.write(json.dumps(resp) + "\n")
                stdout.flush()


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="fenix-block MCP server (stdio)")
    ap.add_argument("--memory-dir", required=True)
    args = ap.parse_args(argv)
    MCPServer(args.memory_dir).serve_stdio()
    return 0
