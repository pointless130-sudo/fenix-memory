# fenix-block — Project Constitution

Read this before every task. It governs all work in this repository.

---

## 1. What this project is

**fenix-block** is an open framework that gives any AI agent memory that persists,
costs less to recall, and can be proved.

It replaces the transcript — a linear log that must be replayed — with an addressable,
content-addressed structure that can be queried. Cost then tracks relevance instead of
history, and the same structure extends onto a blockchain later if third parties ever
need to trust the record.

**Domain-agnostic by construction.** What changes between projects is a shard schema and
a policy predicate. The substrate does not change. If a build requires changing the
substrate to fit a domain, that is a defect, not a feature.

**Licence:** MIT. Public good.

### The adoption ladder

| Stage | Adds | Gives | Chain? |
|---|---|---|---|
| **L0** | Typed content-addressed shards + manifest | Lower recall cost, durable memory, portability | No |
| **L1** | Local Merkle roots + decision receipts | Tamper-evident history, deterministic replay | No |
| L2 | On-chain anchoring of roots | Third parties can verify history is intact | Yes |
| L3 | Identity, ZK policy proofs, shared registries, settlement | Portable reputation, provable compliance | Yes |

**Current scope is L0 + L1 only.** No chain, no wallet, no gas, no ZK. Anything in this
repo that reaches for a chain right now is out of scope — say so and stop.

---

## 2. Agent Operating Protocol

Mode: deterministic solver board. Non-trivial tasks run the full board. Trivial tasks
skip the board but never the principles.

### Core principles

1. **Critical thinking on every task.** Push back with evidence if the request conflicts
   with known facts.
2. **Use what works.** Never modify working code, configs, or deployed systems unless the
   task requires it.
3. **Pull live artifacts, never assume.** Read the actual file, DB row, process list, or
   log before claiming it exists. Training data is not evidence.
4. **Ask before build.** Present design/mockup for approval before any non-trivial
   implementation.
5. **No repeated mistakes.** Consult Gotchas (§5) before touching anything listed. Add new
   mistakes immediately.
6. **Trace every data/signal flow end-to-end.** Surface discrepancies; never paper over
   them.
7. **Think from the end-user's perspective.** Walk the real use-case flow, including
   failure paths.
8. **Formalize first.** Frame constraints, invariants, inputs/outputs, and state machines
   before acting. Ambiguity → escalate, never guess.
9. **"Verified" means passes an explicit, reproducible check** (tests, type-check, build,
   mock e2e). A compiling build is a candidate, not a result.

### Stakes classifier

- **CRITICAL** (production systems, keys, money): full board + live-artifact pull +
  mock-first + human gate on design and irreversible steps.
- **STANDARD** (features, APIs, schema changes): full board.
- **SCRATCH** (local experiments): principles only.

**Phase A0 is STANDARD.** No keys, no funds, no production system exists.

### The board

- **Builder** — formalizes, implements, runs build/type-check. Write access only.
  Never self-certifies.
- **Reviewer** (read+execute) — adversarial check of model vs requirement and code vs
  model. Verdict: `CONFIRMED` or `REJECTED: <specific defect>`.
- **QA** (read+execute) — writes checks from the formal spec (not from Builder's notes),
  walks the end-user flow including failure paths.
  Verdict: `PASS` or `FAIL: <exact failing case>`.

### Budget

≤ 2 build+verify cycles. Second failure = full stop + escalation packet. Attempt 2 must
state in one line what attempt 1's exact failure was and why the fix addresses it. No
blind retries.

---

## 3. Invariants

These are properties QA verifies. A build that compiles but violates any of these is not
a result. Marked with the stage at which each becomes testable.

| ID | Invariant | Stage |
|---|---|---|
| **I1** | **Append-only.** No committed state is ever overwritten or deleted. History is monotonic. | L0 |
| **I2** | **Resolvability.** Every decision hash resolves to a retrievable memory root that verifies against its Merkle proof. | L1 |
| **I3** | **Cold-start reconstruction.** An agent with zero session state rebuilds working context from root + manifest alone. No transcript replay. | L0 |
| **I4** | **Economic gating.** An action is taken only when expected value exceeds cost + threshold. At L0/L1 the cost term is inference, not gas. | L0 |
| **I5** | **Sublinear recall.** Recall cost is O(relevant shards), never O(history). | L0 |
| I6 | Disclosure minimality. A verifier learns exactly the predicate proved and nothing more. | L3 |
| **I7** | **Portability.** Memory exports and re-imports across model vendors with no loss of verifiability. | L0 |
| **I8** | **Fork integrity.** A memory forked at root R verifies independently against R, and its provenance pointer to R is preserved and checkable. | L1 |
| **I9** | **Replay determinism.** Re-running a committed decision against its committed inputs reproduces the recorded output byte-for-byte, or reports an explicit model-drift diff. Silent divergence is a defect. | L1 |
| I10 | Encrypted-shard soundness. Inclusion and policy verify without the verifier holding the key. | L3 |
| I11 | Read-side trust. Registry writes unrestricted; trust is a read-time filter, never a write-time gate. | L2 |
| **I12** | **Surface parity.** The same operation issued via any interface produces byte-identical committed state. No interface is privileged. | L0 |

**Bold rows are in scope now.** I5 is the headline claim — the benchmark exists to prove it.

---

## 4. Reference stack

| Role | Tier | Notes |
|---|---|---|
| Decide step | Mid-tier reasoning model | Structured judgement with tool use. Bulk of spend. |
| Watcher / triage | Cheapest current model | Answers only "did anything change enough to wake the decider?" |
| Escalation | Top-tier reasoning model | Cases the decide step flags as beyond confidence. |
| Build-time codegen | Top-tier reasoning model | Once at build time. Not in the loop, not a recurring cost. |

**Harness: provider SDK + a purpose-written loop. No agent framework.** This is a
measurement requirement, not a preference — the benchmark compares two retrieval
strategies, and a framework that manages context on the agent's behalf sits between the
agent and the thing being measured.

**Pin one model version per benchmark run and record it with every figure.**

---

## 5. Gotchas

Verified facts. Consult before touching anything listed. Append immediately when a new
one is confirmed against real artifacts — never write churn, never record suspicions.

### G1 — Prompt cache TTL bounds the caching win
Provider cache lifetimes max out at one hour. An agent invoked less often than the cache
lives gets **zero** cross-invocation cache benefit regardless of how stable its keys are.
Cache-stability savings are real only *within* an invocation, or for agents running more
frequently than the TTL.
**Consequence:** report cold-start cost and within-invocation hit rate as separate
figures. Never publish a blended number — it conceals which mechanism produced the saving
and flatters high-frequency deployments.

### G2 — Tokenizers are not stable across model generations
A model generation change can shift token counts for identical text by tens of percent. A
benchmark run spanning a model change measures the tokenizer, not the architecture.
**Consequence:** pin the model version for the duration of a run. Record it with the
result. Treat any model change as a new run.

### G3 — Cadence is a deployment property, not an architectural one
An earlier plan assumed a multi-hour polling loop. That was inherited from an unrelated
document and is wrong. Polling a clock makes cost track time instead of opportunity —
the exact error this project exists to fix.
**Consequence:** the substrate assumes no cadence. Prefer event-driven triggers, or a
cheap watcher escalating to an expensive decider.

### G4 — Trust belongs at the read path, not the write path
For any shared registry: gating writes suppresses the network effect that makes it
valuable. Attributing every entry and filtering at read time by author and corroboration
preserves the network effect without inheriting spam exposure.
**Consequence:** never add a write gate to fix a trust problem. Fix it in the query client.

### G5 — Encryption envelope and provenance pointer must ship in v1
Both are cheap to carry and impossible to retrofit. Committed history written without a
provenance pointer can never gain one.
**Consequence:** every shard carries both fields from the first commit, even though the
features consuming them land later.

### G6 — The core SDK surface is three verbs and stays three
`commit`, `recall`, `prove`. Everything else (`fork`, `export`, `import`, `replay`,
`gotchas`) lives in a secondary namespace.
**Consequence:** adoption dies at the fourth core verb. Adding one is a spec change
requiring human approval, not an implementation detail.

### G7 — A flat manifest makes recall O(history)
Verified by the A0 benchmark: with a single flat manifest indexing every shard, Arm B's
per-task input cost grew 21x from 10 to 1,000 decisions, because every decision adds a
manifest entry that every recall must load. A two-level manifest (constant-size root
manifest → per-type sub-manifests) restored flat cost (1.00x growth), because a typed
query never loads the decisions index.
**Consequence:** the manifest loaded on recall must be constant-size; per-type indexes are
loaded only for queried types. Residual: recall within a type is O(shards-of-that-type),
so the manifest-growth question (brief §11) stays open for types whose key count grows
unboundedly.

---

## 6. Standing rules

- No deployment touching real funds, live keys, or public commitments proceeds without
  explicit human approval **at the time of the action**. Silence is not approval; silence
  means do nothing.
- No live keys until every check in the verification plan passes in mock mode.
- No unverified performance numbers, ever. Every published figure comes from `/bench` on
  a recorded model version. "Substantially faster" without a number is a spec violation.
- Every REJECT or QA fail that reveals a new verified fact is appended to §5 before close.
