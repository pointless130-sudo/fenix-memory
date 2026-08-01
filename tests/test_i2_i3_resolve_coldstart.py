"""I2 — every decision resolves to a root that verifies against its Merkle
proof. I3 — cold-start reconstruction from root + manifest alone."""
from sdk.memory import Memory
from sdk.shard import Shard

FIXED = "2026-07-31T00:00:00+00:00"


def _build(tmp_path):
    mem = Memory(tmp_path / "m")
    mem.commit(
        [Shard(type="facts", key=f"fact.{i}", body={"i": i}, created_at=FIXED) for i in range(5)],
        committed_at=FIXED,
    )
    roots = []
    for d in range(10):
        roots.append(mem.commit(
            [Shard(type="decisions", key=f"decision.{d}",
                   body={"inputs": {}, "policy": {}, "action": "approve",
                         "outcome": {}, "model_version": "mock-model-v0"},
                   created_at=FIXED)],
            committed_at=FIXED,
        ))
    return mem, roots


def test_i2_every_decision_resolves_and_proves(tmp_path):
    mem, roots = _build(tmp_path)
    for d, root in enumerate(roots):
        proof = mem.prove({"type": "decisions", "key": f"decision.{d}", "root": root})
        assert Memory.verify(proof)
        assert proof["merkle_root"] == mem.commit_obj(root)["merkle_root"]
    # negative case: tampered proof fails
    proof = mem.prove({"type": "decisions", "key": "decision.0"})
    proof["merkle_root"] = "0" * 64
    assert not Memory.verify(proof)


def test_i3_cold_start_reconstruction(tmp_path):
    mem, roots = _build(tmp_path)
    expected = {(s.type, s.key): s.body for s in mem.recall({})}
    head = mem.head()
    del mem  # zero session state

    fresh = Memory(tmp_path / "m")  # only root + manifest on disk
    assert fresh.head() == head
    rebuilt = {(s.type, s.key): s.body for s in fresh.recall({})}
    assert rebuilt == expected  # working context reconstructed, no transcript replay
    assert fresh.verify_chain()
