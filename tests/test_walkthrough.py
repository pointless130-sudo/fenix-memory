"""End-user walkthrough in mock mode, including every failure path:
unresolvable reference, failed commit, DEGRADED entry, human recovery.
(Verification plan §8.8.) Runs with no network and no API key (§8.9 —
enforced suite-wide by conftest's socket guard)."""
import os
import stat

import pytest

from agents.codegotchas.agent import CodeGotchasAgent, DegradedError
from sdk.memory import Memory
from sdk.shard import Shard

FIXED = "2026-07-31T00:00:00+00:00"
CLOCK = lambda: FIXED  # noqa: E731


def _agent(tmp_path, name="m"):
    mem = Memory(tmp_path / name)
    agent = CodeGotchasAgent(mem, clock=CLOCK, gate_threshold=0.0)
    agent.record_gotcha("gotcha.race", {"class": "concurrency", "failure": "double spend on retry"},
                        tags=("retry", "concurrency"))
    return agent, mem


def test_happy_path_walkthrough(tmp_path):
    agent, mem = _agent(tmp_path)
    # user proposes a change resembling a known failure -> agent warns
    out = agent.run_task({"id": "w1", "change": "add retry loop to payment call",
                          "tags": ["retry"], "expected_value": 50.0})
    assert out["action"] == "warn"
    assert out["trace"] == ["IDLE", "LOAD", "DECIDE", "GATE", "COMMIT", "PROVE", "IDLE"]
    assert Memory.verify(out["proof"])
    # user proposes an unrelated change -> approved
    out2 = agent.run_task({"id": "w2", "change": "rename a variable",
                           "tags": ["style"], "expected_value": 50.0})
    assert out2["action"] == "approve"


def test_failure_path_unresolvable_reference(tmp_path):
    agent, mem = _agent(tmp_path)
    # externally damage the store: the gotcha shard object disappears
    cid = mem.index()["gotchas"]["gotcha.race"]["cid"]
    path = mem.store._path(cid)
    os.chmod(path, stat.S_IWRITE)
    os.remove(path)  # simulated disk loss, not an API path — none exists

    with pytest.raises(DegradedError):
        agent.run_task({"id": "f1", "change": "add retry loop", "tags": ["retry"],
                        "expected_value": 50.0})
    assert agent.state == "DEGRADED"
    assert any("DEGRADED" in a for a in agent.alerts)  # alert emitted


def test_failure_path_commit_failure_retains_prior_root(tmp_path, monkeypatch):
    agent, mem = _agent(tmp_path)
    prior = mem.head()
    monkeypatch.setattr(mem.store, "put", lambda data: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(DegradedError):
        agent.run_task({"id": "f2", "change": "safe change", "tags": ["style"],
                        "expected_value": 50.0})
    assert agent.state == "DEGRADED"
    assert mem.head() == prior  # last known-good root preserved


def test_degraded_never_auto_recovers_and_human_recovery_works(tmp_path, monkeypatch):
    agent, mem = _agent(tmp_path)
    monkeypatch.setattr(mem.store, "put", lambda data: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(DegradedError):
        agent.run_task({"id": "f3", "change": "x", "tags": [], "expected_value": 50.0})
    monkeypatch.undo()  # the underlying fault is fixed...
    with pytest.raises(DegradedError):
        # ...but the agent still refuses: DEGRADED never auto-recovers into COMMIT
        agent.run_task({"id": "f4", "change": "y", "tags": [], "expected_value": 50.0})
    with pytest.raises(DegradedError):
        agent.record_gotcha("gotcha.new", {"f": "z"})

    agent.human_recover("operator inspected store, fault cleared")
    assert agent.state == "IDLE"
    out = agent.run_task({"id": "f5", "change": "y", "tags": [], "expected_value": 50.0})
    assert out["action"] == "approve"


def test_manifest_stays_under_soft_limit_at_small_scale(tmp_path):
    """Observability for the 2KB manifest target (brief §2)."""
    agent, mem = _agent(tmp_path)
    root = mem.commit([Shard(type="facts", key="fact.arch", body={"stack": "py"},
                             created_at=FIXED)], committed_at=FIXED)
    assert mem.commit_obj(root)["manifest_bytes"] < 2048
