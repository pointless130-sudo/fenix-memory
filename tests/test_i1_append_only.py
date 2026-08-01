"""I1 — Append-only. No committed state is ever overwritten or deleted.
Includes the overwrite fuzzing from the verification plan (§8.1)."""
import os
import stat

import pytest

from sdk.cid import canonical_json, cid_of
from sdk.memory import Memory
from sdk.shard import Shard
from sdk.store import IntegrityError, ObjectStore

FIXED = "2026-07-31T00:00:00+00:00"


def _shard(key="fact.a", body=None):
    return Shard(type="facts", key=key, body=body or {"x": 1}, created_at=FIXED)


def test_no_delete_or_overwrite_surface_exists(tmp_path):
    store = ObjectStore(tmp_path)
    public = [n for n in dir(store) if not n.startswith("_")]
    for verb in ("delete", "remove", "overwrite", "update", "clear", "pop", "truncate"):
        assert not any(verb in n.lower() for n in public), f"forbidden verb surface: {verb}"
    mem = Memory(tmp_path / "m")
    public = [n for n in dir(mem) if not n.startswith("_")]
    for verb in ("delete", "remove", "overwrite", "clear", "pop", "truncate"):
        assert not any(verb in n.lower() for n in public), f"forbidden verb surface: {verb}"


def test_put_is_idempotent_and_never_replaces(tmp_path):
    store = ObjectStore(tmp_path)
    data = canonical_json({"a": 1})
    cid = store.put(data)
    assert store.put(data) == cid  # idempotent
    # Files are written read-only as defense in depth.
    mode = os.stat(store._path(cid)).st_mode
    assert not (mode & stat.S_IWRITE)


def test_internal_write_path_cannot_clobber(tmp_path):
    """Fuzz the internal path: force different bytes at an existing address."""
    store = ObjectStore(tmp_path)
    data = canonical_json({"a": 1})
    cid = store.put(data)
    path = store._path(cid)
    # Simulate a colliding write attempt through the only write primitive:
    with pytest.raises(OSError):
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    # And the API-level guard: same address, different bytes -> IntegrityError.
    os.chmod(path, stat.S_IWRITE)
    path.write_bytes(canonical_json({"tampered": True}))
    with pytest.raises(IntegrityError):
        store.get(cid)  # tamper is detected on read
    with pytest.raises(IntegrityError):
        store.put(data)  # tamper is also detected on the write path


def test_recommitting_a_key_never_rewrites_history(tmp_path):
    mem = Memory(tmp_path)
    r1 = mem.commit([_shard(body={"v": "one"})], committed_at=FIXED)
    r2 = mem.commit([_shard(body={"v": "two"})], committed_at=FIXED)
    assert r1 != r2
    old = mem.recall({"type": "facts", "key": "fact.a"}, root_cid=r1)
    new = mem.recall({"type": "facts", "key": "fact.a"}, root_cid=r2)
    assert old[0].body == {"v": "one"}  # history is monotonic: r1 still resolves v1
    assert new[0].body == {"v": "two"}
    # head chain records both roots, in order
    lines = (mem.dir / "heads.log").read_text("ascii").split()
    assert lines == [r1, r2]


def test_commit_objects_chain_backwards(tmp_path):
    mem = Memory(tmp_path)
    r1 = mem.commit([_shard()], committed_at=FIXED)
    r2 = mem.commit([_shard(key="fact.b")], committed_at=FIXED)
    c2 = mem.commit_obj(r2)
    assert c2["prev_root"] == r1
    assert mem.commit_obj(r1)["prev_root"] is None
