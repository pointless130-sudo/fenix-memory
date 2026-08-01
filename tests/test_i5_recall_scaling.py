"""I5 — Sublinear recall: recall cost is O(relevant shards), never O(history).

Cost here is measured structurally — the number of store objects read to
answer a query — which is the model-independent driver of token cost.
"""
from sdk.memory import Memory
from sdk.shard import Shard

FIXED = "2026-07-31T00:00:00+00:00"


def _memory_with_history(tmp_path, n_decisions):
    mem = Memory(tmp_path / f"m{n_decisions}")
    mem.commit(
        [Shard(type="gotchas", key=f"gotcha.g{i}", body={"failure": f"p{i}"},
               created_at=FIXED, tags=(f"topic{i}",)) for i in range(10)],
        committed_at=FIXED,
    )
    for d in range(n_decisions):
        mem.commit(
            [Shard(type="decisions", key=f"decision.{d}", body={"d": d}, created_at=FIXED)],
            committed_at=FIXED,
        )
    return mem


def _count_reads(mem, query):
    reads = {"n": 0}
    orig = mem.store.get

    def counting_get(cid):
        reads["n"] += 1
        return orig(cid)

    mem.store.get = counting_get
    try:
        result = mem.recall(query)
    finally:
        mem.store.get = orig
    return reads["n"], result


def test_recall_cost_constant_as_history_grows(tmp_path):
    costs = []
    for n in (10, 50, 200):
        mem = _memory_with_history(tmp_path, n)
        reads, result = _count_reads(mem, {"type": "gotchas", "contains": "topic3"})
        assert [s.key for s in result] == ["gotcha.g3"]
        costs.append(reads)
    # identical read count at every history size: O(relevant), not O(history)
    assert costs[0] == costs[1] == costs[2], f"recall cost scaled with history: {costs}"


def test_unfiltered_recall_is_the_only_o_history_path(tmp_path):
    mem = _memory_with_history(tmp_path, 20)
    reads_all, result = _count_reads(mem, {})
    assert len(result) == 30  # 10 gotchas + 20 decisions
    reads_one, _ = _count_reads(mem, {"type": "gotchas", "key": "gotcha.g1"})
    assert reads_one < reads_all
