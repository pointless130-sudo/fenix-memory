"""The core SDK surface: exactly three verbs — commit, recall, prove.

Everything else lives in sdk.ext. Adding a fourth core verb is a spec
change requiring human approval (Gotcha G6).

Manifest is TWO-LEVEL: a root manifest (constant-size: one sub-manifest
CID per shard type) pointing at per-type sub-manifests. This is what
keeps recall O(relevant): a query for gotchas never loads the decisions
index, so recall cost cannot grow with decision history (invariant I5).
A flat manifest was measured to make recall O(history) — see the A0
benchmark — which is why this structure is not optional.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .cid import canonical_json
from .merkle import inclusion_proof, merkle_root, verify_proof
from .shard import Shard
from .store import IntegrityError, ObjectStore

MANIFEST_SOFT_LIMIT_BYTES = 2048  # applies to the root manifest


class Memory:
    """A single agent memory: content-addressed store + hash-chained roots."""

    def __init__(self, root_dir: str | os.PathLike):
        self.dir = Path(root_dir)
        self.store = ObjectStore(self.dir)
        self._heads_path = self.dir / "heads.log"

    # ---- head chain (append-only ref log; committed state lives in objects) ----

    def head(self) -> str | None:
        if not self._heads_path.exists():
            return None
        lines = self._heads_path.read_text("ascii").split()
        return lines[-1] if lines else None

    def _append_head(self, root_cid: str) -> None:
        with open(self._heads_path, "a", encoding="ascii") as f:
            f.write(root_cid + "\n")

    def _provenance(self) -> str | None:
        p = self.dir / "PROVENANCE"
        return p.read_text("ascii").strip() if p.exists() else None

    # ---- internal resolution ----

    def _get_obj(self, cid: str) -> dict:
        return json.loads(self.store.get(cid).decode("utf-8"))

    def commit_obj(self, root_cid: str | None = None) -> dict | None:
        cid = root_cid or self.head()
        return self._get_obj(cid) if cid else None

    def manifest(self, root_cid: str | None = None) -> dict:
        """The ROOT manifest: {"v": 1, "types": {type: sub_manifest_cid}}."""
        c = self.commit_obj(root_cid)
        if c is None:
            return {"v": 1, "types": {}}
        return self._get_obj(c["manifest_cid"])

    def _sub(self, sub_cid: str) -> dict:
        """A per-type sub-manifest: {"shards": {key: {"cid":..., "tags":[...]}}}."""
        return self._get_obj(sub_cid)

    def index(self, root_cid: str | None = None) -> dict:
        """Full index type -> key -> entry. O(history) BY DESIGN — used only
        by commit/prove/verify walks, never by recall."""
        root = self.manifest(root_cid)
        return {t: self._sub(c)["shards"] for t, c in root["types"].items()}

    # ================= verb 1: commit =================

    def commit(self, shards: list[Shard], committed_at: str = "") -> str:
        """Commit new shards; returns the new root CID.

        Append-only: prior roots, manifests, and shard objects are never
        touched. A re-used (type, key) points the new manifest at the new
        shard; every earlier root still resolves the earlier one.
        """
        prev = self.head()
        root_manifest = self.manifest(prev)
        types = dict(root_manifest["types"])

        touched: dict[str, dict] = {}
        for shard in shards:
            if shard.type not in touched:
                touched[shard.type] = (
                    self._sub(types[shard.type]) if shard.type in types
                    else {"v": 1, "shards": {}}
                )
            scid = self.store.put(canonical_json(shard.to_obj()))
            touched[shard.type]["shards"][shard.key] = {
                "cid": scid,
                "tags": list(shard.tags),
            }
        for stype, sub in touched.items():
            types[stype] = self.store.put(canonical_json(sub))

        root_bytes = canonical_json({"v": 1, "types": types})
        manifest_cid = self.store.put(root_bytes)

        all_cids = [
            e["cid"]
            for sub_cid in types.values()
            for e in self._sub(sub_cid)["shards"].values()
        ]
        prev_obj = self.commit_obj(prev)
        commit = {
            "v": 1,
            "kind": "commit",
            "manifest_cid": manifest_cid,
            "merkle_root": merkle_root(all_cids),
            "prev_root": prev,
            "seq": (prev_obj["seq"] + 1) if prev_obj else 0,
            "committed_at": committed_at,
            "provenance": self._provenance(),
            "manifest_bytes": len(root_bytes),  # observability for the 2KB target
        }
        root_cid = self.store.put(canonical_json(commit))
        self._append_head(root_cid)
        return root_cid

    # ================= verb 2: recall =================

    def recall(self, query: dict, root_cid: str | None = None) -> list[Shard]:
        """Resolve only matching shards — never scan history.

        Query fields (all optional, ANDed):
          type     — exact shard type
          key      — exact key
          prefix   — key prefix
          contains — substring matched against key and tags (manifest-level
                     metadata only; shard bodies are never searched)
        Loads: root manifest + only the sub-manifests for queried types +
        only the matched shards. Cost is O(relevant), by construction (I5).
        """
        root = self.manifest(root_cid)
        out: list[Shard] = []
        for stype, sub_cid in root["types"].items():
            if "type" in query and query["type"] != stype:
                continue  # sub-manifest for this type is never even loaded
            for key, entry in self._sub(sub_cid)["shards"].items():
                if "key" in query and query["key"] != key:
                    continue
                if "prefix" in query and not key.startswith(query["prefix"]):
                    continue
                if "contains" in query:
                    needle = query["contains"]
                    if needle not in key and not any(needle in t for t in entry["tags"]):
                        continue
                out.append(Shard.from_obj(self._get_obj(entry["cid"])))
        return out

    # ================= verb 3: prove =================

    def prove(self, claim: dict) -> dict:
        """Merkle inclusion proof that a shard is part of a committed root.

        Claim: {"shard_cid": ...} or {"type": ..., "key": ...}, plus
        optional "root" (defaults to head). The proof verifies offline via
        Memory.verify — no store access needed.
        """
        root_cid = claim.get("root") or self.head()
        if root_cid is None:
            raise ValueError("nothing committed yet")
        idx = self.index(root_cid)
        if "shard_cid" in claim:
            target = claim["shard_cid"]
        else:
            try:
                target = idx[claim["type"]][claim["key"]]["cid"]
            except KeyError:
                raise KeyError(f"no shard {claim.get('type')}/{claim.get('key')} at {root_cid}")
        all_cids = [e["cid"] for by_key in idx.values() for e in by_key.values()]
        if target not in all_cids:
            raise KeyError(f"shard {target} not included at root {root_cid}")
        return {
            "shard_cid": target,
            "path": inclusion_proof(all_cids, target),
            "merkle_root": self.commit_obj(root_cid)["merkle_root"],
            "root_cid": root_cid,
        }

    @staticmethod
    def verify(proof: dict) -> bool:
        return verify_proof(
            proof["shard_cid"],
            [tuple(p) for p in proof["path"]],
            proof["merkle_root"],
        )

    # ---- integrity walk used by import/fork (not a public verb) ----

    def verify_chain(self, root_cid: str | None = None) -> bool:
        """Walk the commit chain from root to genesis, verifying every object."""
        cid = root_cid or self.head()
        while cid is not None:
            commit = self._get_obj(cid)  # get() hash-verifies
            idx = self.index(cid)
            all_cids = [e["cid"] for by_key in idx.values() for e in by_key.values()]
            if merkle_root(all_cids) != commit["merkle_root"]:
                raise IntegrityError(f"merkle root mismatch at {cid}")
            for c in all_cids:
                self.store.get(c)
            cid = commit["prev_root"]
        return True
