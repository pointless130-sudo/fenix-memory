# fenix-block — Phase A0

An L0/L1 memory substrate for AI agents: typed, content-addressed shards,
a sub-2KB manifest, Merkle-rooted append-only history, and decision
receipts — plus the benchmark that proves the headline claim (invariant
I5): **recall cost is O(relevant shards), never O(history)**.

No blockchain, no wallet, no gas, no network, no API key. See
`CLAUDE.md` (constitution) and `PHASE_A0_BRIEF.md` (scope).

## Layout

```
/sdk        core three verbs: commit, recall, prove  (+ ext: export, import, fork, replay)
/agents/codegotchas   reference agent — consults verified gotchas before approving a change
/bench      the benchmark harness — the deliverable
/tests      one property test per in-scope invariant, incl. negative cases
```

## Run the benchmark

```bash
python -m bench.run
```

Writes `bench/results/result.json` and `result.txt`. Compares naive
transcript replay (Arm A) against addressed recall (Arm B) at 10 / 100 /
1,000 committed decisions on identical task sets. Reports input/output
tokens per task, latency, cold-start cost per invocation and
within-invocation cache hit rate — the last two separately, never
blended (Gotcha G1). The model/tokenizer version is recorded with every
figure (Gotcha G2). Default mode is mock: figures are valid for the
scaling *shape*, not absolute dollars, and are labeled as such.

## Run the tests

```bash
python -m pytest tests -q
```

The suite runs with no network (enforced by a socket guard) and no API
key. Requires Python 3.11+ and pytest.

## Core SDK

```python
from sdk import Memory, Shard

mem = Memory("./mymemory")
root = mem.commit([Shard(type="gotchas", key="gotcha.x",
                         body={"class": "db", "failure": "..."},
                         created_at="2026-07-31T00:00:00+00:00",
                         tags=("db",))])
shards = mem.recall({"type": "gotchas", "contains": "db"})
proof  = mem.prove({"type": "gotchas", "key": "gotcha.x"})
assert Memory.verify(proof)      # verifies offline, no store access
```

The core surface is exactly three verbs and stays three (Gotcha G6).
`fork`, `export`, `import_`, `replay` live in `sdk.ext`.

Addressing is CIDv1 (raw codec, sha2-256, base32) — byte-compatible with
IPFS so L2 anchoring drops in later without rewriting committed history.
Every shard carries an encryption envelope and a provenance pointer from
its first commit (Gotcha G5), consumed by later phases.
