# fenix-memory

**Durable, addressable, provable memory for any AI agent — and recall
cost that stays flat as history grows.**

Agent memory today is a transcript: it grows forever, must be replayed
on every cold start, and dies with the session. fenix-memory replaces it
with typed, content-addressed shards, a constant-size manifest,
Merkle-rooted append-only history, and decision receipts. The measured
result (invariant I5): **recall cost is O(relevant shards), never
O(history)** — measured with real API token counts on a pinned model
(claude-haiku-4-5), naive transcript replay grew **26.3x** from 10 to
1,000 committed decisions while addressed recall stayed **flat at
1.00x** (~2,770 tokens/task) — **47x cheaper per task** at 1,000
decisions, with 3.6x lower latency. Reproduce it: `python -m bench.run`
(offline mock mode) or `python -m bench.run --real --cap 3.0` (your own
API key, hard spend cap enforced in code).

Everything in this repository is **MIT-licensed and runs entirely
locally**: no blockchain, no wallet, no account, no network, no API key.
Part of the Fenix family alongside fenix-yield and fenix-intel. Hosted
extras (cloud sync, team memory, hosted verification/anchoring, the
dashboard) are a separate paid service — see `NOTICE.md`; the local
substrate is free forever.

**New here? Start with [QUICKSTART.md](QUICKSTART.md) — 10 minutes to
provable agent memory.**

See `CLAUDE.md` (project constitution) and `PHASE_A0_BRIEF.md` (build
brief) for how this was built and verified.

## Layout

```
/sdk        core three verbs: commit, recall, prove  (+ ext: export, import, fork, replay)
/agents/codegotchas   reference agent — consults verified gotchas before approving a change
/bench      the benchmark harness — the A0 deliverable
/mcp_server MCP server (stdio, zero-dependency): memory_commit / memory_recall / memory_prove
/sidecar    local HTTP sidecar: POST /commit /recall /prove, GET /status
/cli        operator tooling: init, status (incl. DEGRADED + alerts), commit, recall,
            prove, replay, export, import, fork
/skills     invocable skill (the judgement layer) + portable constitution template
/tests      one property test per in-scope invariant, incl. negative cases
```

## Interface surfaces (A1)

Every surface is a thin shell over one shared dispatch core, so the same
operation issued via SDK, MCP, sidecar, or CLI produces byte-identical
committed state (invariant I12 — tested across a real process boundary).

MCP (stdio), e.g. for Claude Code:

```json
{"mcpServers": {"fenix-block": {"command": "python",
  "args": ["-m", "mcp_server", "--memory-dir", "/path/to/memory"],
  "cwd": "/path/to/fenix-block"}}}
```

Sidecar for non-MCP runtimes: `python -m sidecar --memory-dir ./mymemory --port 7691`

CLI: `python -m cli --dir ./mymemory status` (add `--watch 300 --on-degraded "<cmd>"`
to run a command the moment the agent enters DEGRADED).

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

## Free vs. hosted

| | |
|---|---|
| **Free forever (this repo, MIT)** | The full local substrate: SDK, MCP server, sidecar, CLI, the `/fenix-memory` skill, benchmark, tests. Your memory, your disk, verifiable offline. |
| **Fenix portal (paid, coming)** | Cloud memory sync + encrypted backup across machines · team shared memory with per-member attribution · hosted verifier + on-chain anchoring (the L2 trust layer as a service) · dashboard: browse shards, replay decisions, cost analytics. |

The free tier is not a demo — it is the complete L0/L1 architecture and
will stay MIT. The paid tier is infrastructure we run so you don't have to.

## Roadmap

- **Phase A (done):** L0/L1 substrate, benchmark, reference agent, MCP /
  sidecar / CLI / skill surfaces.
- **Phase B:** on-chain anchoring of memory roots, Merkle inclusion +
  policy predicate proofs, encrypted private shards.
- **Phase C:** fork-a-brain, permissionless shared gotchas registry,
  public verifier, quickstart.

## License

MIT — see `LICENSE`. Code is free forever; the Fenix names and the
hosted services are not part of the grant — see `NOTICE.md`.
