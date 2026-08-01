"""Canonical serialization and CIDv1 addressing.

Addressing is CID-compatible (CIDv1, raw codec 0x55, sha2-256 multihash,
base32-lower multibase) so IPFS drops in at L2 without rewriting committed
history. Implemented from the multiformats specs with stdlib only, so the
full suite runs with no network and no third-party dependency.
"""
from __future__ import annotations

import base64
import hashlib
import json

_RAW_CODEC = 0x55
_SHA2_256 = 0x12
_CIDV1 = 0x01


def canonical_json(obj) -> bytes:
    """Canonical bytes for an object: UTF-8, sorted keys, no whitespace.

    The same logical object must produce the same bytes on any machine —
    every address in the system derives from this.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def cid_of(data: bytes) -> str:
    """CIDv1(raw, sha2-256) of raw bytes, base32-lower with 'b' multibase prefix."""
    digest = hashlib.sha256(data).digest()
    cid_bytes = (
        _varint(_CIDV1)
        + _varint(_RAW_CODEC)
        + _varint(_SHA2_256)
        + _varint(len(digest))
        + digest
    )
    b32 = base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
    return "b" + b32


def cid_of_obj(obj) -> str:
    return cid_of(canonical_json(obj))
