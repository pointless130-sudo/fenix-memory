# Phase A0 — Build Brief

**Read `CLAUDE.md` first.** It governs everything below and its Gotchas override any
assumption you hold.

**Stakes: STANDARD.** Full board. No keys, no funds, no production system.

---

## 0. Scope note — read before planning

Phase A as specified in the architecture document is large: memory DAG, SDK, MCP server,
invocable skill, HTTP sidecar, CLI, anchor contract, benchmark harness, plus two
reference agents.

**A0 is the smallest slice that proves the central claim.** Everything this project is
marketed on rests on one number: that recall cost stays flat as history grows (I5). If
that number does not materialise, no interface work matters. If it does, the interfaces
are straightforward.

Build A0. Stop. Show the number. A1 (MCP server, skill, sidecar, CLI) follows only after
A0's benchmark produces a real result.

---

## 1. Objective

Produce a working L0/L1 memory substrate and a benchmark that measures it, plus one
reference agent that uses it for real.

**The deliverable is a number**, reproducible by a stranger: recall cost at 10, 100, and
1,000 committed decisions, measured under naive transcript replay versus addressed
recall, on identical task sets.

---

## 2. In scope

- **Shard schema** — four types: `facts`, `decisions`, `gotchas`, `artifacts`
- **Manifest** — indexes shards by type and key; target under 2KB
- **Content-addressed local store** — hash-addressed, immutable, append-only
- **Merkle DAG** + root computation
- **Decision receipts** — inputs, policy applied, action, outcome
- **Core SDK (Python)** — `commit(state) -> root`, `recall(query) -> shards`,
  `prove(claim) -> proof`
- **Secondary namespace** — `export`, `import`, `fork`, `replay`
- **Benchmark harness** (`/bench`)
- **Reference agent** (`/agents/codegotchas`) — a coding assistant that accumulates
  verified gotchas and consults them before proposing a change resembling a known failure

## 3. Out of scope — do not build

Blockchain anything. IPFS. Wallets, keys, gas. ZK proofs. ERC-8004 identity. The shared
gotchas registry (local private store only at this stage). x402. MCP server. HTTP
sidecar. CLI. TypeScript SDK. The public verifier. The second reference agent.

If a task seems to require any of these, **stop and escalate** — it means the formal
model is wrong.

---

## 4. Invariants in scope

Verify: **I1, I2, I3, I4, I5, I7, I8, I9, I12.**

Out of scope: I6, I10, I11 (all require L2/L3).

**I5 is the headline.** Recall cost must be O(relevant shards), never O(history).

I12 at this stage means: the same commit issued through the SDK directly and through the
reference agent produces byte-identical roots.

---

## 5. Design constraints

- **Python 3.11+.** TypeScript port is A1, not now.
- **Hashing must be CID-compatible** so IPFS drops in at L2 without rewriting committed
  history. Local store now; addressing scheme final now.
- **Every shard carries an encryption envelope field and a provenance pointer** from the
  first commit, even though nothing consumes them yet. See Gotcha G5 — these cannot be
  retrofitted.
- **Core SDK stays at exactly three verbs.** See G6. Adding a fourth is a spec change
  requiring human approval.
- **Mock mode for every external dependency**, including the model provider. The full
  test suite must run with no network and no API key.
- **No agent framework.** Provider SDK plus a purpose-written loop. See §4 of `CLAUDE.md`
  — this is a measurement requirement.
- **Append-only is structural, not conventional.** There must be no code path, public or
  internal, that overwrites or deletes a committed shard.

---

## 6. State machine

Every state has a defined transition for both success and failure. Transitions must be
total.

```
IDLE      → trigger fires → LOAD
LOAD      → fetch manifest, resolve required shards
            failure: unresolvable reference → DEGRADED
DECIDE    → evaluate policy against inputs → action or no-op
GATE      → apply I4; if expected value <= cost + threshold,
            write a no-op receipt locally → IDLE
COMMIT    → write shards, compute new root
            failure: retain prior root → DEGRADED
PROVE     → generate local inclusion proof, publish with the receipt
DEGRADED  → halt actions, preserve last known-good root, emit alert,
            await human. NEVER auto-recovers into COMMIT.
```

The substrate assumes **no invocation cadence** (Gotcha G3). `IDLE → LOAD` fires on
whatever trigger the deployment defines.

---

## 7. Benchmark specification

This is the deliverable. Build it carefully.

**Compare two arms on identical task sets:**
- **Arm A — naive:** full transcript replay on every invocation
- **Arm B — addressed:** manifest load, resolve only matching shards

**Measure at 10, 100, and 1,000 committed decisions:**
- input tokens per task
- output tokens per task
- wall-clock latency per task
- cold-start cost per invocation
- within-invocation cache hit rate

**Report cold-start and within-invocation cache figures separately.** Never blend them —
see Gotcha G1. A blended number hides which mechanism produced the saving.

**Record the model version with every figure** — see Gotcha G2.

**Pass condition:** Arm B's per-task cost does not scale with history. If it does, that
is a real finding and must be reported as one, not tuned away.

---

## 8. Verification plan (QA runs these from this spec, not from Builder's notes)

1. **Append-only fuzzing** — attempt overwrite via every public and internal path. All
   must fail. (I1)
2. **Cold-start reconstruction** — wipe all session state, rebuild from root + manifest,
   diff against expected working context. (I3)
3. **Recall scaling** — measure at 10 / 100 / 1,000 decisions; confirm cost does not
   scale with history. (I5)
4. **Portability round-trip** — export a bundle, re-import, confirm the root still
   verifies and context reconstructs. (I7)
5. **Fork integrity** — fork at root R, diverge, confirm both branches verify
   independently and the provenance pointer to R survives. (I8)
6. **Replay determinism** — replay 100 committed decisions; each must byte-match or
   produce an explicit diff. Silent divergence fails. (I9)
7. **Surface parity** — identical commit via SDK and via the reference agent produces the
   same root. (I12)
8. **End-user walkthrough in mock mode**, including every failure path: unresolvable
   reference, failed commit, DEGRADED entry, human recovery.
9. **Full suite runs with no network and no API key.**

---

## 9. Repository layout

```
/sdk/               core three verbs + secondary namespace
/agents/codegotchas/ reference agent
/bench/             the harness — the deliverable
/tests/             one property test per in-scope invariant, incl. negative cases
CLAUDE.md           constitution
PHASE_A0_BRIEF.md   this file
README.md           what it is, how to run the benchmark
```

---

## 10. Process

1. **Formalize.** Produce the shard schema, manifest format, addressing scheme, and
   module boundaries. Surface every ambiguity as a question.
   **Then STOP and present for approval. Do not write implementation code before
   approval.**
2. Build against the approved model.
3. Reviewer subagent (read+execute, explicitly instructed not to modify files).
4. QA subagent (read+execute), given this spec only.
5. Ship or loop. ≤ 2 cycles.
6. Append any new verified fact to `CLAUDE.md` §5 before close.

---

## 11. Open questions to resolve during formalization

- Shard granularity: what is the natural unit for a `gotcha` — one failure, or one
  failure class?
- Query interface for `recall`: exact key lookup, type filter, semantic match, or a
  combination? This choice directly determines whether I5 holds.
- Manifest growth: at what shard count does a flat 2KB manifest stop working, and what
  replaces it?
- Compaction on commit: what triggers it, and what is the summarization policy?
