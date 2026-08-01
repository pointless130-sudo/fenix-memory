"""I7 — portability round-trip. I8 — fork integrity."""
import pytest

from sdk import ext
from sdk.memory import Memory
from sdk.shard import Shard
from sdk.store import IntegrityError

FIXED = "2026-07-31T00:00:00+00:00"


def _build(tmp_path, name="src"):
    mem = Memory(tmp_path / name)
    mem.commit([Shard(type="facts", key="fact.a", body={"x": 1}, created_at=FIXED)],
               committed_at=FIXED)
    mem.commit([Shard(type="gotchas", key="gotcha.g1", body={"f": "boom"},
                      created_at=FIXED, tags=("t1",))], committed_at=FIXED)
    return mem


def test_i7_export_import_roundtrip(tmp_path):
    src = _build(tmp_path)
    head = ext.export(src, str(tmp_path / "bundle.json"))
    dest = ext.import_(str(tmp_path / "bundle.json"), str(tmp_path / "dest"))
    assert dest.head() == head  # same root: provably the same memory
    assert dest.verify_chain()
    a = {(s.type, s.key): s.body for s in src.recall({})}
    b = {(s.type, s.key): s.body for s in dest.recall({})}
    assert a == b  # working context reconstructs identically


def test_i7_tampered_bundle_rejected(tmp_path):
    import json
    src = _build(tmp_path)
    ext.export(src, str(tmp_path / "bundle.json"))
    bundle = json.loads((tmp_path / "bundle.json").read_text("utf-8"))
    victim = next(iter(bundle["objects"]))
    bundle["objects"][victim] = "dGFtcGVyZWQ="  # 'tampered'
    (tmp_path / "bad.json").write_text(json.dumps(bundle), encoding="utf-8")
    with pytest.raises(IntegrityError):
        ext.import_(str(tmp_path / "bad.json"), str(tmp_path / "dest2"))


def test_i8_fork_integrity(tmp_path):
    src = _build(tmp_path)
    R = src.head()
    forked = ext.fork(src, R, str(tmp_path / "fork"))

    # diverge both branches
    src.commit([Shard(type="facts", key="fact.src", body={"branch": "src"},
                      created_at=FIXED)], committed_at=FIXED)
    f_root = forked.commit([Shard(type="facts", key="fact.fork", body={"branch": "fork"},
                                  created_at=FIXED)], committed_at=FIXED)

    # both branches verify independently
    assert src.verify_chain()
    assert forked.verify_chain()

    # provenance pointer to R is preserved and checkable
    assert (forked.dir / "PROVENANCE").read_text("ascii").strip() == R
    assert forked.commit_obj(f_root)["provenance"] == R
    # and the fork still resolves pre-fork history against R
    assert forked.recall({"type": "facts", "key": "fact.a"}, root_cid=R)[0].body == {"x": 1}
