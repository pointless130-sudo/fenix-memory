"""A1 — interface surfaces.

I12 at full width: the identical commit issued via SDK, MCP (real stdio
loop), sidecar dispatch, and CLI (subprocess) produces byte-identical
root CIDs. Plus MCP protocol conformance, sidecar error handling, and
the CLI operator walkthrough including DEGRADED surfacing.
"""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agents.codegotchas.agent import CodeGotchasAgent
from cli.main import main as cli_main
from mcp_server.server import MCPServer
from sdk.api import DispatchError, dispatch
from sdk.memory import Memory
from sdk.shard import Shard
from sidecar.server import handle_request

REPO = Path(__file__).resolve().parents[1]
FIXED = "2026-07-31T00:00:00+00:00"
CLOCK = lambda: FIXED  # noqa: E731

SHARD_PAYLOAD = {
    "type": "gotchas",
    "key": "gotcha.parity",
    "body": {"class": "test", "failure": "surfaces diverged"},
    "created_at": FIXED,
    "tags": ["parity"],
}


def _mcp_call(memory_dir, tool, arguments):
    server = MCPServer(str(memory_dir))
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": tool, "arguments": arguments}})
    assert "error" not in resp, resp
    assert resp["result"]["isError"] is False, resp
    return json.loads(resp["result"]["content"][0]["text"])


def test_i12_full_width_parity(tmp_path):
    roots = {}

    # 1 — SDK directly
    mem = Memory(tmp_path / "sdk")
    shard = Shard(type="gotchas", key="gotcha.parity",
                  body={"class": "test", "failure": "surfaces diverged"},
                  created_at=FIXED, tags=("parity",))
    roots["sdk"] = mem.commit([shard], committed_at=FIXED)

    # 2 — dispatch core (what every surface routes through)
    roots["dispatch"] = dispatch("commit", {
        "memory_dir": str(tmp_path / "dispatch"),
        "shards": [SHARD_PAYLOAD], "committed_at": FIXED,
    })["root"]

    # 3 — MCP tools/call
    roots["mcp"] = _mcp_call(tmp_path / "mcp", "memory_commit",
                             {"shards": [SHARD_PAYLOAD], "committed_at": FIXED})["root"]

    # 4 — sidecar HTTP handler
    status, payload = handle_request(
        "POST", "/commit",
        json.dumps({"shards": [SHARD_PAYLOAD], "committed_at": FIXED}).encode("utf-8"),
        str(tmp_path / "sidecar"),
    )
    assert status == 200, payload
    roots["sidecar"] = payload["root"]

    # 5 — CLI subprocess (real process boundary)
    shards_file = tmp_path / "shards.json"
    shards_file.write_text(json.dumps([SHARD_PAYLOAD]), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "cli", "--dir", str(tmp_path / "cli"), "commit",
         "--file", str(shards_file), "--committed-at", FIXED],
        cwd=REPO, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    roots["cli"] = json.loads(out.stdout)["root"]

    assert len(set(roots.values())) == 1, f"surfaces diverged: {roots}"


def test_mcp_stdio_round_trip(tmp_path):
    """Drive the real newline-delimited stdio loop end to end."""
    lines = [
        {"jsonrpc": "2.0", "id": 0, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "memory_commit",
                    "arguments": {"shards": [SHARD_PAYLOAD], "committed_at": FIXED}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "memory_recall",
                    "arguments": {"query": {"type": "gotchas", "contains": "parity"}}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "memory_prove",
                    "arguments": {"claim": {"type": "gotchas", "key": "gotcha.parity"}}}},
        "this is not json",
        {"jsonrpc": "2.0", "id": 5, "method": "no/such/method"},
    ]
    stdin = io.StringIO("\n".join(l if isinstance(l, str) else json.dumps(l) for l in lines) + "\n")
    stdout = io.StringIO()
    MCPServer(str(tmp_path / "m")).serve_stdio(stdin=stdin, stdout=stdout)
    responses = [json.loads(l) for l in stdout.getvalue().splitlines()]
    by_id = {r.get("id"): r for r in responses}

    assert by_id[0]["result"]["serverInfo"]["name"] == "fenix-block"
    assert [t["name"] for t in by_id[1]["result"]["tools"]] == [
        "memory_commit", "memory_recall", "memory_prove"]  # exactly three (G6)
    root = json.loads(by_id[2]["result"]["content"][0]["text"])["root"]
    recalled = json.loads(by_id[3]["result"]["content"][0]["text"])["shards"]
    assert [s["key"] for s in recalled] == ["gotcha.parity"]
    proof = json.loads(by_id[4]["result"]["content"][0]["text"])
    assert proof["verified"] is True
    assert proof["proof"]["root_cid"] == root
    assert by_id[None]["error"]["code"] == -32700  # parse error, server survived
    assert by_id[5]["error"]["code"] == -32601  # method not found, server survived


def test_mcp_tool_error_is_isError_not_crash(tmp_path):
    server = MCPServer(str(tmp_path / "m"))
    resp = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                          "params": {"name": "memory_commit", "arguments": {"shards": []}}})
    assert resp["result"]["isError"] is True


def test_sidecar_handler_errors(tmp_path):
    d = str(tmp_path / "m")
    assert handle_request("GET", "/nope", b"", d)[0] == 404
    assert handle_request("GET", "/commit", b"", d)[0] == 405
    assert handle_request("POST", "/status", b"", d)[0] == 405
    assert handle_request("POST", "/commit", b"not json", d)[0] == 400
    assert handle_request("POST", "/commit", b"[]", d)[0] == 400
    status, payload = handle_request("GET", "/status", b"", d)
    assert status == 200 and payload["head"] is None and payload["state"] == "IDLE"


def test_no_fourth_core_tool_surface(tmp_path):
    """ext ops exist on CLI (operator surface) but NOT as MCP tools or sidecar routes."""
    from mcp_server.server import TOOLS
    from sidecar.server import ROUTES
    assert {t["name"] for t in TOOLS} == {"memory_commit", "memory_recall", "memory_prove"}
    assert ROUTES == {"commit", "recall", "prove", "status"}


def test_cli_walkthrough_and_degraded_surfacing(tmp_path, capsys, monkeypatch):
    d = str(tmp_path / "m")
    shards_file = tmp_path / "s.json"
    shards_file.write_text(json.dumps([SHARD_PAYLOAD]), encoding="utf-8")
    bundle = str(tmp_path / "bundle.json")

    assert cli_main(["--dir", d, "init"]) == 0
    capsys.readouterr()
    assert cli_main(["--dir", d, "commit", "--file", str(shards_file),
                     "--committed-at", FIXED]) == 0
    assert json.loads(capsys.readouterr().out)["root"].startswith("b")

    assert cli_main(["--dir", d, "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["seq"] == 0 and status["shard_counts"] == {"gotchas": 1}
    assert status["state"] == "IDLE"

    assert cli_main(["--dir", d, "prove", "--claim",
                     json.dumps({"type": "gotchas", "key": "gotcha.parity"})]) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True

    assert cli_main(["--dir", d, "export", "--bundle", bundle]) == 0
    capsys.readouterr()
    assert cli_main(["--dir", str(tmp_path / "m2"), "import", "--bundle", bundle]) == 0
    capsys.readouterr()

    # DEGRADED surfacing: force the agent down, then the operator sees it
    mem = Memory(d)
    agent = CodeGotchasAgent(mem, clock=CLOCK)
    monkeypatch.setattr(mem.store, "put", lambda data: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(Exception):
        agent.run_task({"id": "x", "change": "y", "tags": [], "expected_value": 50.0})
    monkeypatch.undo()

    assert cli_main(["--dir", d, "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"].startswith("DEGRADED")
    assert any("DEGRADED" in a for a in status["alerts"])

    # error path: bad input exits 2 with a JSON error on stderr
    assert cli_main(["--dir", d, "recall", "--query", "not json"]) == 2


def test_cli_replay_matches(tmp_path, capsys):
    d = str(tmp_path / "m")
    mem = Memory(d)
    agent = CodeGotchasAgent(mem, clock=CLOCK)
    agent.run_task({"id": "r1", "change": "safe", "tags": [], "expected_value": 50.0})
    cid = mem.index()["decisions"]["decision.r1"]["cid"]
    assert cli_main(["--dir", d, "replay", "--decision-cid", cid]) == 0
    assert json.loads(capsys.readouterr().out)["match"] is True


def test_a1_did_not_touch_substrate_semantics(tmp_path):
    """The substrate is unchanged: a root committed through any A1 surface
    still verifies with the A0 verbs alone."""
    root = dispatch("commit", {"memory_dir": str(tmp_path / "m"),
                               "shards": [SHARD_PAYLOAD], "committed_at": FIXED})["root"]
    mem = Memory(tmp_path / "m")
    assert mem.head() == root
    assert mem.verify_chain()
