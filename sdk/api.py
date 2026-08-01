"""Shared dispatch core for every interface surface (MCP, sidecar, CLI).

All surfaces call this one function, and all commits route through the
identical Shard construction path — so surface parity (invariant I12) is
structural, not incidental. Timestamps are caller-supplied: the same
request is byte-identical through any door.

This is NOT a fourth core verb (G6): it is plumbing that exposes the
same three verbs (plus the ext namespace and read-only status) to
out-of-process callers.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import ext
from .memory import Memory
from .shard import Shard

OPS = ("commit", "recall", "prove", "status", "replay", "export", "import", "fork")


class DispatchError(Exception):
    pass


def _memory(params: dict) -> Memory:
    d = params.get("memory_dir")
    if not d:
        raise DispatchError("memory_dir is required")
    return Memory(d)


def _shard_from_payload(p: dict) -> Shard:
    tags = p.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise DispatchError("tags must be a list of strings")
    try:
        return Shard(
            type=p["type"],
            key=p["key"],
            body=p["body"],
            created_at=p["created_at"],
            tags=tuple(tags),
        )
    except (KeyError, ValueError) as exc:
        raise DispatchError(f"invalid shard payload: {exc}") from exc


def dispatch(op: str, params: dict) -> dict:
    """Execute one operation; returns a JSON-serializable result dict.

    Raises DispatchError on bad input — surfaces map it to their own
    error shape (JSON-RPC error, HTTP 400, CLI exit code).
    """
    if op == "commit":
        mem = _memory(params)
        shards = [_shard_from_payload(p) for p in params.get("shards", [])]
        if not shards:
            raise DispatchError("commit requires at least one shard")
        root = mem.commit(shards, committed_at=params.get("committed_at", ""))
        return {"root": root}

    if op == "recall":
        mem = _memory(params)
        shards = mem.recall(params.get("query", {}), root_cid=params.get("root"))
        return {"shards": [s.to_obj() for s in shards]}

    if op == "prove":
        mem = _memory(params)
        try:
            proof = mem.prove(params["claim"])
        except (KeyError, ValueError) as exc:
            raise DispatchError(str(exc)) from exc
        return {"proof": proof, "verified": Memory.verify(proof)}

    if op == "status":
        mem = _memory(params)
        head = mem.head()
        commit = mem.commit_obj(head) if head else None
        counts = {t: len(by_key) for t, by_key in mem.index(head).items()} if head else {}
        state_path = Path(mem.dir) / "STATE"
        alerts_path = Path(mem.dir) / "alerts.log"
        return {
            "head": head,
            "seq": commit["seq"] if commit else None,
            "manifest_bytes": commit["manifest_bytes"] if commit else 0,
            "shard_counts": counts,
            "provenance": commit["provenance"] if commit else None,
            "state": state_path.read_text("utf-8").strip() if state_path.exists() else "IDLE",
            "alerts": alerts_path.read_text("utf-8").splitlines()[-5:] if alerts_path.exists() else [],
        }

    if op == "replay":
        from agents.codegotchas.agent import decide_policy  # default decider

        mem = _memory(params)
        try:
            return ext.replay(mem, params["decision_cid"], decide_policy)
        except (KeyError, ValueError) as exc:
            raise DispatchError(f"replay failed: {exc}") from exc

    if op == "export":
        mem = _memory(params)
        head = ext.export(mem, params["bundle_path"], root_cid=params.get("root"))
        return {"head": head, "bundle_path": params["bundle_path"]}

    if op == "import":
        mem = ext.import_(params["bundle_path"], params["memory_dir"])
        return {"head": mem.head()}

    if op == "fork":
        src = _memory(params)
        forked = ext.fork(src, params["at_root"], params["dest_dir"])
        return {"head": forked.head(), "provenance": params["at_root"]}

    raise DispatchError(f"unknown op {op!r}; valid ops: {OPS}")


def dispatch_json(op: str, params_json: str) -> str:
    return json.dumps(dispatch(op, json.loads(params_json)))
