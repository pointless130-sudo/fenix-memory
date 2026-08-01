"""codegotchas — the reference agent.

A coding assistant that accumulates verified gotchas and consults them
before proposing a change resembling a known failure. Purpose-written
loop over a provider interface — no agent framework (measurement
requirement, CLAUDE.md §4). Runs entirely in mock mode by default: no
network, no API key.

State machine (total; every state has success and failure transitions):

    IDLE → LOAD → DECIDE → GATE → COMMIT → PROVE → IDLE
    LOAD failure (unresolvable reference) → DEGRADED
    COMMIT failure (prior root retained)  → DEGRADED
    GATE below threshold → no-op receipt → IDLE
    DEGRADED: halt, keep last known-good root, await human.
              NEVER auto-recovers into COMMIT.
"""
from __future__ import annotations

import datetime
import time
from typing import Callable

from sdk.memory import Memory
from sdk.shard import Shard

MOCK_MODEL_VERSION = "mock-model-v0"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class MockProvider:
    """Deterministic offline stand-in for a model provider.

    Token accounting uses a pinned deterministic approximation
    (len(text) // 4), recorded as part of the model version string so no
    figure can be mistaken for a real-tokenizer measurement (Gotcha G2).
    """

    model_version = MOCK_MODEL_VERSION
    tokenizer = "mock-tokenizer-v0 (chars//4)"

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def complete(self, context: str, prompt: str) -> tuple[str, int, int]:
        """Returns (response_text, input_tokens, output_tokens)."""
        response = f"ack:{len(context)}:{len(prompt)}"
        return response, self.count_tokens(context + prompt), self.count_tokens(response)


def decide_policy(inputs: dict, policy: dict) -> dict:
    """The deterministic decision function — pure over committed inputs.

    Kept module-level and side-effect-free so ext.replay can re-run any
    committed decision byte-for-byte (invariant I9).
    """
    if policy.get("name") != "consult-gotchas-v1":
        raise ValueError(f"unknown policy {policy!r}")
    if inputs.get("gated"):
        # I4 no-op receipts replay through the same pure function.
        return {
            "action": "no-op",
            "outcome": {"gated": True, "expected_value": inputs["expected_value"],
                        "cost": inputs["cost"]},
            "model_version": inputs.get("model_version", MOCK_MODEL_VERSION),
        }
    matched = inputs.get("matched_gotchas", [])
    action = "warn" if matched else "approve"
    return {
        "action": action,
        "outcome": {
            "change": inputs["change"],
            "matched_gotchas": matched,
            "proceed": action == "approve",
        },
        "model_version": inputs.get("model_version", MOCK_MODEL_VERSION),
    }


class DegradedError(Exception):
    pass


class CodeGotchasAgent:
    POLICY = {"name": "consult-gotchas-v1", "rule": "never approve a change matching a known gotcha"}

    def __init__(
        self,
        memory: Memory,
        provider: MockProvider | None = None,
        clock: Callable[[], str] = _utc_now,
        gate_threshold: float = 0.0,
    ):
        self.memory = memory
        self.provider = provider or MockProvider()
        self.clock = clock
        self.gate_threshold = gate_threshold
        self.state = "IDLE"
        self.degraded_reason: str | None = None
        self.alerts: list[str] = []

    # ---- human recovery: the ONLY exit from DEGRADED ----

    def human_recover(self, ack: str) -> None:
        if self.state != "DEGRADED":
            return
        self.degraded_reason = None
        self.state = "IDLE"
        self._alert(f"human recovery acknowledged: {ack}")
        (self.memory.dir / "STATE").write_text("IDLE", encoding="utf-8")

    def _alert(self, line: str) -> None:
        """Alerts are surfaced in-process AND persisted (append-only log +
        STATE ref) so an operator's `cli status` can see DEGRADED — a halt
        nobody is told about is a failure, not a safe state."""
        self.alerts.append(line)
        with open(self.memory.dir / "alerts.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _enter_degraded(self, reason: str) -> None:
        self.state = "DEGRADED"
        self.degraded_reason = reason
        self._alert(f"DEGRADED: {reason}")
        (self.memory.dir / "STATE").write_text(f"DEGRADED: {reason}", encoding="utf-8")

    # ---- shard constructors (deterministic; shared with the parity test, I12) ----

    def receipt_shard(self, task_id: str, inputs: dict, decision: dict, ts: str) -> Shard:
        return Shard(
            type="decisions",
            key=f"decision.{task_id}",
            body={
                "inputs": inputs,
                "policy": self.POLICY,
                "action": decision["action"],
                "outcome": decision["outcome"],
                "model_version": decision["model_version"],
            },
            created_at=ts,
            tags=tuple(sorted(inputs.get("tags", ()))),
        )

    def record_gotcha(self, key: str, body: dict, tags: tuple[str, ...] = ()) -> str:
        """Append a verified failure. One shard per failure; `class` in body groups them."""
        if self.state == "DEGRADED":
            raise DegradedError(self.degraded_reason or "agent is DEGRADED")
        shard = Shard(type="gotchas", key=key, body=body, created_at=self.clock(), tags=tags)
        return self.memory.commit([shard], committed_at=self.clock())

    # ---- the loop ----

    def run_task(self, task: dict) -> dict:
        """task = {"id", "change", "tags", "expected_value"}"""
        if self.state == "DEGRADED":
            raise DegradedError(self.degraded_reason or "agent is DEGRADED")
        trace = ["IDLE"]
        prior_root = self.memory.head()
        started = time.perf_counter()
        tokens_in = tokens_out = 0

        # LOAD — manifest, then only the shards this task needs
        self.state = "LOAD"
        trace.append("LOAD")
        try:
            matched: list[Shard] = []
            seen: set[str] = set()
            for tag in task.get("tags", ()):
                for s in self.memory.recall({"type": "gotchas", "contains": tag}):
                    if s.key not in seen:
                        seen.add(s.key)
                        matched.append(s)
        except Exception as exc:  # unresolvable reference
            self._enter_degraded(f"LOAD failure: {exc}")
            raise DegradedError(self.degraded_reason) from exc

        # DECIDE — provider consulted for token accounting; the committed
        # decision itself is the pure policy function over committed inputs.
        self.state = "DECIDE"
        trace.append("DECIDE")
        context = "\n".join(f"[gotcha {s.key}] {s.body}" for s in matched)
        _, t_in, t_out = self.provider.complete(context, task["change"])
        tokens_in += t_in
        tokens_out += t_out
        inputs = {
            "change": task["change"],
            "tags": sorted(task.get("tags", ())),
            "matched_gotchas": sorted(s.key for s in matched),
            "model_version": self.provider.model_version,
        }
        decision = decide_policy(inputs, self.POLICY)

        # GATE — invariant I4: act only when expected value exceeds cost + threshold.
        self.state = "GATE"
        trace.append("GATE")
        cost = (tokens_in + tokens_out) / 1000.0  # inference cost proxy at L0/L1
        gated = task.get("expected_value", 0.0) <= cost + self.gate_threshold
        if gated:
            inputs = {**inputs, "gated": True,
                      "expected_value": task.get("expected_value", 0.0), "cost": cost}
            decision = decide_policy(inputs, self.POLICY)

        # COMMIT
        self.state = "COMMIT"
        trace.append("COMMIT")
        ts = self.clock()
        shard = self.receipt_shard(task["id"], inputs, decision, ts)
        try:
            root = self.memory.commit([shard], committed_at=ts)
        except Exception as exc:
            # Prior root is retained by construction — commit never mutates it.
            assert self.memory.head() == prior_root
            self._enter_degraded(f"COMMIT failure: {exc}")
            raise DegradedError(self.degraded_reason) from exc

        if gated:
            self.state = "IDLE"
            trace.append("IDLE")
            return {
                "task": task["id"], "action": "no-op", "root": root, "trace": trace,
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "latency_s": time.perf_counter() - started,
                "model_version": self.provider.model_version,
            }

        # PROVE
        self.state = "PROVE"
        trace.append("PROVE")
        proof = self.memory.prove({"type": "decisions", "key": f"decision.{task['id']}", "root": root})
        assert Memory.verify(proof)

        self.state = "IDLE"
        trace.append("IDLE")
        return {
            "task": task["id"], "action": decision["action"],
            "matched_gotchas": inputs["matched_gotchas"],
            "root": root, "proof": proof, "trace": trace,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "latency_s": time.perf_counter() - started,
            "model_version": self.provider.model_version,
        }
