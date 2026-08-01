"""Binary Merkle tree over sorted shard CIDs, with inclusion proofs."""
from __future__ import annotations

import hashlib


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def leaf_hash(cid: str) -> bytes:
    return _h(b"leaf:" + cid.encode("ascii"))


def _pair(left: bytes, right: bytes) -> bytes:
    return _h(b"node:" + left + right)


def merkle_root(cids: list[str]) -> str:
    """Root over the sorted CID list. Empty list has a defined sentinel root."""
    if not cids:
        return _h(b"empty").hex()
    level = [leaf_hash(c) for c in sorted(cids)]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])  # duplicate-last for odd levels
        level = [_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()


def inclusion_proof(cids: list[str], target: str) -> list[tuple[str, str]]:
    """Path of (side, sibling_hex) from the target leaf to the root."""
    ordered = sorted(cids)
    if target not in ordered:
        raise KeyError(f"{target} not in leaf set")
    idx = ordered.index(target)
    level = [leaf_hash(c) for c in ordered]
    path: list[tuple[str, str]] = []
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        sib = idx ^ 1
        side = "L" if sib < idx else "R"
        path.append((side, level[sib].hex()))
        level = [_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return path


def verify_proof(target: str, path: list[tuple[str, str]], root_hex: str) -> bool:
    node = leaf_hash(target)
    for side, sibling_hex in path:
        sib = bytes.fromhex(sibling_hex)
        node = _pair(sib, node) if side == "L" else _pair(node, sib)
    return node.hex() == root_hex
