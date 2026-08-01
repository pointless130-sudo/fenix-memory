"""/bench — the deliverable.

Measures recall cost under two arms on identical task sets:
  Arm A (naive):     full transcript replay on every invocation
  Arm B (addressed): manifest load, resolve only matching shards

At 10 / 100 / 1,000 committed decisions it reports, per arm:
  input tokens per task, output tokens per task, wall-clock latency per
  task, cold-start cost per invocation, and within-invocation cache hit
  rate — the last two as SEPARATE figures (Gotcha G1: a blended number
  conceals which mechanism produced the saving).

Mock mode (default, no network, no key): token figures use a pinned
deterministic tokenizer approximation and are valid for the SCALING
SHAPE of the claim (flat vs linear), not for absolute dollar costs. The
model/tokenizer version is recorded with every figure (Gotcha G2).

Run:  python -m bench.run [--out bench/results]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.codegotchas.agent import MockProvider  # noqa: E402
from sdk.cid import canonical_json  # noqa: E402
from sdk.memory import Memory  # noqa: E402
from sdk.shard import Shard  # noqa: E402

HISTORY_SIZES = (10, 100, 1000)
TASKS_PER_SET = 20
STEPS_PER_INVOCATION = 3  # multi-step reasoning against the same loaded context
FIXED_CLOCK = "2026-07-31T00:00:00+00:00"

GOTCHA_POOL = 20  # fixed-size knowledge base, identical across history sizes


def build_history(base_dir: Path, n_decisions: int) -> Memory:
    """A memory with a fixed knowledge base and n committed decision receipts."""
    mem = Memory(base_dir / f"history_{n_decisions}")
    kb: list[Shard] = []
    for i in range(GOTCHA_POOL):
        kb.append(Shard(
            type="gotchas", key=f"gotcha.g{i:03d}",
            body={"class": f"class-{i % 5}", "failure": f"pattern p{i} broke the build",
                  "repro": f"touch module m{i} without pinning dep d{i}"},
            created_at=FIXED_CLOCK, tags=(f"topic{i:03d}", f"class-{i % 5}"),
        ))
        kb.append(Shard(
            type="facts", key=f"fact.f{i:03d}",
            body={"statement": f"module m{i} is owned by team t{i % 3}"},
            created_at=FIXED_CLOCK, tags=(f"topic{i:03d}",),
        ))
    mem.commit(kb, committed_at=FIXED_CLOCK)
    for d in range(n_decisions):
        receipt = Shard(
            type="decisions", key=f"decision.d{d:05d}",
            body={"inputs": {"change": f"historic change #{d} touching module m{d % GOTCHA_POOL}",
                             "tags": [f"topic{d % GOTCHA_POOL:03d}"]},
                  "policy": {"name": "consult-gotchas-v1"},
                  "action": "approve", "outcome": {"proceed": True},
                  "model_version": MockProvider.model_version},
            created_at=FIXED_CLOCK, tags=(f"topic{d % GOTCHA_POOL:03d}",),
        )
        mem.commit([receipt], committed_at=FIXED_CLOCK)
    return mem


def task_set() -> list[dict]:
    """Identical across history sizes; each task needs a constant number of shards."""
    return [{"id": f"task{t:02d}", "change": f"proposed change touching module m{t % GOTCHA_POOL}",
             "tag": f"topic{t % GOTCHA_POOL:03d}"} for t in range(TASKS_PER_SET)]


def arm_a_context(mem: Memory) -> str:
    """Naive: serialize the entire history — every shard ever committed."""
    everything = mem.recall({})  # deliberately unfiltered: this IS the transcript replay
    return "\n".join(canonical_json(s.to_obj()).decode("utf-8") for s in everything)


def arm_b_context(mem: Memory, tag: str) -> str:
    """Addressed: root manifest + relevant sub-manifests + matching shards.

    Queries are TYPED (gotchas, facts) so the decisions index is never
    loaded — that is the mechanism under measurement. The context charges
    honestly for everything the agent must read: the root manifest, the
    sub-manifests it opened, and the resolved shards.
    """
    root_manifest = mem.manifest()
    parts = [canonical_json(root_manifest).decode("utf-8")]
    for stype in ("gotchas", "facts"):
        sub_cid = root_manifest["types"][stype]
        parts.append(mem.store.get(sub_cid).decode("utf-8"))
        for s in mem.recall({"type": stype, "contains": tag}):
            parts.append(canonical_json(s.to_obj()).decode("utf-8"))
    return "\n".join(parts)


def run_invocation(provider: MockProvider, context: str, prompt: str) -> dict:
    """One cold-start invocation: multi-step loop over a stable context prefix.

    Cache simulation follows provider prefix-caching semantics: a step
    whose context prefix is byte-identical to the previous step's reads
    it at cache-hit cost. Cold-start cost (step 1, nothing cached) and
    within-invocation hit rate are reported separately (G1).
    """
    t0 = time.perf_counter()
    total_in = total_out = cached = 0
    prev_prefix = None
    for step in range(STEPS_PER_INVOCATION):
        step_prompt = f"{prompt} [step {step}]"
        _, t_in, t_out = provider.complete(context, step_prompt)
        total_in += t_in
        total_out += t_out
        if prev_prefix == context:
            cached += provider.count_tokens(context)
        prev_prefix = context
    return {
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cold_start_tokens": provider.count_tokens(context + f"{prompt} [step 0]"),
        "cache_hit_rate": cached / total_in if total_in else 0.0,
        "latency_s": time.perf_counter() - t0,
    }


def run(out_dir: Path) -> dict:
    provider = MockProvider()
    base = out_dir / "state"
    results: dict = {
        "model_version": provider.model_version,
        "tokenizer": provider.tokenizer,
        "note": ("MOCK-MODE figures: valid for the scaling shape (flat vs linear), "
                 "not absolute cost. Cold-start and cache figures are separate by design."),
        "tasks_per_set": TASKS_PER_SET,
        "steps_per_invocation": STEPS_PER_INVOCATION,
        "history_sizes": {},
    }
    for n in HISTORY_SIZES:
        print(f"building history: {n} committed decisions ...", flush=True)
        mem = build_history(base, n)
        tasks = task_set()
        per_arm: dict = {}
        for arm, ctx_fn in (("A_naive", lambda t: arm_a_context(mem)),
                            ("B_addressed", lambda t: arm_b_context(mem, t["tag"]))):
            rows = [run_invocation(provider, ctx_fn(t), t["change"]) for t in tasks]
            per_arm[arm] = {
                "input_tokens_per_task": statistics.mean(r["input_tokens"] for r in rows),
                "output_tokens_per_task": statistics.mean(r["output_tokens"] for r in rows),
                "latency_s_per_task": statistics.mean(r["latency_s"] for r in rows),
                "cold_start_tokens_per_invocation": statistics.mean(r["cold_start_tokens"] for r in rows),
                "within_invocation_cache_hit_rate": statistics.mean(r["cache_hit_rate"] for r in rows),
            }
        results["history_sizes"][str(n)] = per_arm

    # Pass condition: Arm B per-task cost does not scale with history.
    b_lo = results["history_sizes"][str(HISTORY_SIZES[0])]["B_addressed"]["input_tokens_per_task"]
    b_hi = results["history_sizes"][str(HISTORY_SIZES[-1])]["B_addressed"]["input_tokens_per_task"]
    a_lo = results["history_sizes"][str(HISTORY_SIZES[0])]["A_naive"]["input_tokens_per_task"]
    a_hi = results["history_sizes"][str(HISTORY_SIZES[-1])]["A_naive"]["input_tokens_per_task"]
    results["scaling"] = {
        "arm_A_growth_10_to_1000": a_hi / a_lo,
        "arm_B_growth_10_to_1000": b_hi / b_lo,
        "pass_condition": "Arm B per-task input cost does not scale with history (growth <= 1.25x)",
        "pass": b_hi / b_lo <= 1.25,
    }
    return results


def render_table(results: dict) -> str:
    lines = [
        f"model: {results['model_version']}   tokenizer: {results['tokenizer']}",
        "",
        f"{'N':>5} | {'arm':<11} | {'in tok/task':>12} | {'out tok/task':>12} | "
        f"{'latency s':>10} | {'cold-start tok':>14} | {'cache hit':>9}",
        "-" * 90,
    ]
    for n, arms in results["history_sizes"].items():
        for arm, m in arms.items():
            lines.append(
                f"{n:>5} | {arm:<11} | {m['input_tokens_per_task']:>12.1f} | "
                f"{m['output_tokens_per_task']:>12.1f} | {m['latency_s_per_task']:>10.4f} | "
                f"{m['cold_start_tokens_per_invocation']:>14.1f} | "
                f"{m['within_invocation_cache_hit_rate']:>9.2%}"
            )
    s = results["scaling"]
    lines += [
        "-" * 90,
        f"Arm A growth 10→1000 decisions: {s['arm_A_growth_10_to_1000']:.2f}x",
        f"Arm B growth 10→1000 decisions: {s['arm_B_growth_10_to_1000']:.2f}x",
        f"PASS (I5): {s['pass']}",
        "",
        results["note"],
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).parent / "results"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = run(out)
    (out / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    table = render_table(results)
    (out / "result.txt").write_text(table, encoding="utf-8")
    print(table)
    return 0 if results["scaling"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
