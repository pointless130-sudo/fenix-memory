"""I9 — replay determinism: byte-match or explicit diff; never silent."""
from agents.codegotchas.agent import CodeGotchasAgent, decide_policy
from sdk import ext
from sdk.memory import Memory
from sdk.shard import Shard

FIXED = "2026-07-31T00:00:00+00:00"
CLOCK = lambda: FIXED  # noqa: E731

N_REPLAYS = 100  # verification plan §8.6: replay 100 committed decisions


def _build_history(tmp_path):
    mem = Memory(tmp_path / "m")
    mem.commit([Shard(type="gotchas", key="gotcha.g1", body={"f": "boom"},
                      created_at=FIXED, tags=("risky",))], committed_at=FIXED)
    agent = CodeGotchasAgent(mem, clock=CLOCK, gate_threshold=0.0)
    for i in range(N_REPLAYS):
        tags = ["risky"] if i % 3 == 0 else ["safe"]
        agent.run_task({"id": f"t{i}", "change": f"change #{i}", "tags": tags,
                        "expected_value": 50.0})
    return mem


def _decision_cids(mem):
    return [entry["cid"] for entry in mem.index()["decisions"].values()]


def test_replay_100_decisions_byte_match(tmp_path):
    mem = _build_history(tmp_path)
    cids = _decision_cids(mem)
    assert len(cids) == N_REPLAYS
    for cid in cids:
        result = ext.replay(mem, cid, decide_policy)
        assert result["match"] is True, f"silent divergence would be a defect: {result}"


def test_replay_reports_explicit_diff_on_drift(tmp_path):
    mem = _build_history(tmp_path)
    cid = _decision_cids(mem)[0]

    def drifted_decider(inputs, policy):
        out = decide_policy(inputs, policy)
        out["model_version"] = "mock-model-v1"  # a new model generation
        return out

    result = ext.replay(mem, cid, drifted_decider)
    assert result["match"] is False
    assert result["model_drift"] is True
    assert "recorded" in result and "reproduced" in result  # explicit, never silent
