"""I4 — economic gating. I12 — surface parity: the identical commit issued
via the SDK directly and via the reference agent produces byte-identical roots."""
from agents.codegotchas.agent import CodeGotchasAgent, MockProvider, decide_policy
from sdk.memory import Memory
from sdk.shard import Shard

FIXED = "2026-07-31T00:00:00+00:00"
CLOCK = lambda: FIXED  # noqa: E731


def _seed(mem):
    mem.commit(
        [Shard(type="gotchas", key="gotcha.sqlite-wal",
               body={"class": "db", "failure": "WAL mode dropped under network mount"},
               created_at=FIXED, tags=("sqlite", "db"))],
        committed_at=FIXED,
    )


def test_i4_gate_writes_noop_receipt_and_returns_to_idle(tmp_path):
    mem = Memory(tmp_path / "m")
    _seed(mem)
    agent = CodeGotchasAgent(mem, clock=CLOCK, gate_threshold=100.0)
    out = agent.run_task({"id": "t1", "change": "trivial rename", "tags": [], "expected_value": 0.01})
    assert out["action"] == "no-op"
    assert agent.state == "IDLE"
    receipt = mem.recall({"type": "decisions", "key": "decision.t1"})[0]
    assert receipt.body["action"] == "no-op"
    assert receipt.body["outcome"]["gated"] is True


def test_i4_above_threshold_acts(tmp_path):
    mem = Memory(tmp_path / "m")
    _seed(mem)
    agent = CodeGotchasAgent(mem, clock=CLOCK, gate_threshold=0.0)
    out = agent.run_task({"id": "t2", "change": "switch sqlite journal mode",
                          "tags": ["sqlite"], "expected_value": 50.0})
    assert out["action"] == "warn"  # known gotcha matched
    assert out["matched_gotchas"] == ["gotcha.sqlite-wal"]
    assert Memory.verify(out["proof"])


def test_i12_surface_parity_sdk_vs_agent(tmp_path):
    # Surface 1: the reference agent
    mem_agent = Memory(tmp_path / "agent")
    _seed(mem_agent)
    agent = CodeGotchasAgent(mem_agent, clock=CLOCK, gate_threshold=0.0)
    out = agent.run_task({"id": "t3", "change": "switch sqlite journal mode",
                          "tags": ["sqlite"], "expected_value": 50.0})

    # Surface 2: the SDK directly, issuing the identical commit
    mem_sdk = Memory(tmp_path / "sdk")
    _seed(mem_sdk)
    inputs = {
        "change": "switch sqlite journal mode",
        "tags": ["sqlite"],
        "matched_gotchas": ["gotcha.sqlite-wal"],
        "model_version": MockProvider.model_version,
    }
    decision = decide_policy(inputs, CodeGotchasAgent.POLICY)
    shard = agent.receipt_shard("t3", inputs, decision, FIXED)
    root_sdk = mem_sdk.commit([shard], committed_at=FIXED)

    assert out["root"] == root_sdk  # byte-identical committed state
