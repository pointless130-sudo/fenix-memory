"""Secondary namespace: export, import, fork, replay.

These deliberately live outside the three-verb core surface (Gotcha G6).
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from .cid import canonical_json, cid_of
from .memory import Memory
from .store import IntegrityError

BUNDLE_VERSION = 1


def _reachable(mem: Memory, root_cid: str) -> dict[str, bytes]:
    """Every object reachable from a root: commits, manifests, shards."""
    out: dict[str, bytes] = {}
    cid = root_cid
    while cid is not None:
        out[cid] = mem.store.get(cid)
        commit = json.loads(out[cid].decode("utf-8"))
        mcid = commit["manifest_cid"]
        out[mcid] = mem.store.get(mcid)
        root_manifest = json.loads(out[mcid].decode("utf-8"))
        for sub_cid in root_manifest["types"].values():
            out[sub_cid] = mem.store.get(sub_cid)
            sub = json.loads(out[sub_cid].decode("utf-8"))
            for entry in sub["shards"].values():
                out[entry["cid"]] = mem.store.get(entry["cid"])
        cid = commit["prev_root"]
    return out


def export(mem: Memory, bundle_path: str, root_cid: str | None = None) -> str:
    """Write a versioned, self-verifying memory bundle. Returns the head root."""
    head = root_cid or mem.head()
    if head is None:
        raise ValueError("nothing committed yet")
    objects = _reachable(mem, head)
    bundle = {
        "v": BUNDLE_VERSION,
        "head": head,
        "provenance": mem._provenance(),
        "objects": {c: base64.b64encode(b).decode("ascii") for c, b in objects.items()},
    }
    Path(bundle_path).write_bytes(canonical_json(bundle))
    return head


def import_(bundle_path: str, dest_dir: str) -> Memory:
    """Re-import a bundle, verifying every CID and the full root chain."""
    bundle = json.loads(Path(bundle_path).read_text("utf-8"))
    if bundle["v"] != BUNDLE_VERSION:
        raise ValueError(f"unsupported bundle version {bundle['v']}")
    mem = Memory(dest_dir)
    for declared_cid, b64 in bundle["objects"].items():
        data = base64.b64decode(b64)
        if cid_of(data) != declared_cid:
            raise IntegrityError(f"bundle object {declared_cid} fails hash verification")
        mem.store.put(data)
    if bundle.get("provenance"):
        prov = mem.dir / "PROVENANCE"
        if not prov.exists():
            prov.write_text(bundle["provenance"], encoding="ascii")
    mem._append_head(bundle["head"])
    mem.verify_chain(bundle["head"])
    return mem


def fork(src: Memory, at_root: str, dest_dir: str) -> Memory:
    """Fork a memory at root R. The fork verifies independently against R
    and permanently carries a provenance pointer to R (invariant I8)."""
    dest = Memory(dest_dir)
    for cid, data in _reachable(src, at_root).items():
        dest.store.put(data)
    prov = dest.dir / "PROVENANCE"
    if prov.exists():
        raise IntegrityError("destination already has a provenance pointer")
    prov.write_text(at_root, encoding="ascii")
    dest._append_head(at_root)
    dest.verify_chain(at_root)
    return dest


def replay(mem: Memory, decision_cid: str, decider) -> dict:
    """Re-run a committed decision against its committed inputs (invariant I9).

    `decider(inputs, policy) -> {"action": ..., "outcome": ..., "model_version": ...}`
    Returns {"match": True} on a byte-match, else an explicit diff.
    Silent divergence is impossible by construction: the comparison is on
    canonical bytes of the recorded vs reproduced receipt fields.
    """
    shard_obj = json.loads(mem.store.get(decision_cid).decode("utf-8"))
    if shard_obj["type"] != "decisions":
        raise ValueError(f"{decision_cid} is not a decision shard")
    body = shard_obj["body"]
    reproduced = decider(body["inputs"], body["policy"])
    recorded = {k: body[k] for k in ("action", "outcome", "model_version")}
    if canonical_json(reproduced) == canonical_json(recorded):
        return {"match": True, "decision": decision_cid}
    return {
        "match": False,
        "decision": decision_cid,
        "recorded": recorded,
        "reproduced": reproduced,
        "model_drift": reproduced.get("model_version") != recorded.get("model_version"),
    }
