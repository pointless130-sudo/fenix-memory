# Quickstart — 10 minutes to provable agent memory

No account, no API key, no network. You need Python 3.11+ and git.

## 1. Clone and verify (2 min)

```bash
git clone https://github.com/pointless130-sudo/fenix-memory.git
cd fenix-memory
python -m pip install pytest
python -m pytest tests -q
```

30 tests, one per architectural invariant — append-only history, Merkle
proofs, cold-start reconstruction, replay determinism, surface parity.
They run fully offline (a socket guard enforces it).

## 2. See the headline number (2 min)

```bash
python -m bench.run
```

This measures recall cost at 10 / 100 / 1,000 committed decisions under
two strategies: naive transcript replay vs addressed recall. Expected
shape: replay grows ~28x, addressed recall grows 1.00x — flat. Your
agent's memory stops getting more expensive as it gets more experienced.

## 3. Commit your first memory (3 min)

Create a shard file `shard.json`:

```json
[{"type": "gotchas",
  "key": "gotcha.sqlite-wal",
  "body": {"class": "db", "failure": "WAL mode dropped under network mount"},
  "created_at": "2026-08-01T00:00:00+00:00",
  "tags": ["sqlite", "db"]}]
```

Then:

```bash
python -m cli --dir ./mymem init
python -m cli --dir ./mymem commit --file shard.json --committed-at 2026-08-01T00:00:00+00:00
python -m cli --dir ./mymem recall --query "{\"type\":\"gotchas\",\"contains\":\"db\"}"
python -m cli --dir ./mymem prove --claim "{\"type\":\"gotchas\",\"key\":\"gotcha.sqlite-wal\"}"
```

`commit` returns a root CID — the verifiable fingerprint of your entire
memory. `prove` returns a Merkle inclusion proof with `"verified": true`.

**Tamper test:** flip any byte in any file under `./mymem/objects/`
(clear its read-only flag first) and re-run `recall`. You get an
integrity error, not silently corrupted memory. Flip it back and the
memory recovers — every read verifies bytes against their address.

## 4. Wire it into your agent (3 min)

**Claude Code (MCP):**

```bash
claude mcp add fenix-memory --scope user -- python -m mcp_server --memory-dir /path/to/mymem
```

(Run from the repo directory, or set `PYTHONPATH` to it.) Your agent now
has three tools: `memory_commit`, `memory_recall`, `memory_prove`.

**Any other runtime (HTTP):**

```bash
python -m sidecar --memory-dir ./mymem --port 7691
```

Then `POST http://127.0.0.1:7691/recall` with `{"query": {...}}` — same
three operations, same byte-identical results (that's invariant I12,
and it's tested).

**The discipline (optional but recommended):** copy
`skills/SKILL.md` into your agent's skills as `/fenix-memory` — it
teaches the agent *when* to commit, what counts as a gotcha vs a fact,
and to consult memory before proposing changes that resemble known
failures.

## 5. Where to go next

- `README.md` — architecture, free-vs-hosted split, roadmap
- `CLAUDE.md` — the project constitution: invariants and verified gotchas
- `python -m cli --dir ./mymem export --bundle backup.json` — your whole
  memory as one portable, verifiable file; `import` it anywhere,
  including under a different model vendor
