"""Content-addressed, append-only object store.

Append-only is STRUCTURAL, not conventional (invariant I1): the only write
path opens files with O_CREAT | O_EXCL, so an existing object can never be
truncated or replaced, and there is no delete or overwrite code path in
this module or anywhere above it. After write, objects are marked
read-only as defense in depth.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from .cid import cid_of


class IntegrityError(Exception):
    """Stored bytes do not match their address, or an append-only rule was violated."""


class ObjectStore:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        (self.root / "objects").mkdir(parents=True, exist_ok=True)

    def _path(self, cid: str) -> Path:
        if not cid or "/" in cid or "\\" in cid or "." in cid:
            raise IntegrityError(f"malformed cid: {cid!r}")
        return self.root / "objects" / cid

    def put(self, data: bytes) -> str:
        """Store bytes at their content address. Idempotent; never overwrites."""
        cid = cid_of(data)
        path = self._path(cid)
        if path.exists():
            # Same address must mean same bytes — anything else is corruption.
            if path.read_bytes() != data:
                raise IntegrityError(f"object {cid} exists with different bytes")
            return cid
        # O_EXCL guarantees we can never clobber a committed object, even
        # under a race: the second writer fails and falls into the
        # verify-identical branch above on retry.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.chmod(path, stat.S_IREAD)
        return cid

    def get(self, cid: str) -> bytes:
        """Fetch bytes by address, verifying the hash on every read."""
        path = self._path(cid)
        if not path.exists():
            raise KeyError(cid)
        data = path.read_bytes()
        if cid_of(data) != cid:
            raise IntegrityError(f"object {cid} fails hash verification")
        return data

    def has(self, cid: str) -> bool:
        return self._path(cid).exists()

    def cids(self) -> list[str]:
        return sorted(p.name for p in (self.root / "objects").iterdir())
