---
name: fenix-memory
description: >
  Give this agent durable, addressable, provable memory via the
  fenix-memory substrate. Supplies the judgement the tool layer cannot:
  when a run is worth committing, what belongs in a gotcha versus a
  fact, and when to consult memory before acting.
---

# fenix-memory — the judgement layer

The tools (`memory_commit`, `memory_recall`, `memory_prove` via MCP, or
the HTTP sidecar's `/commit /recall /prove`) supply the *how*. This
skill supplies the *when* and *what*.

## Before acting: always recall first

Before proposing any non-trivial change or decision, query gotchas that
resemble it:

- `memory_recall {"query": {"type": "gotchas", "contains": "<topic tag>"}}`
- If any match, treat them as verified facts, not suggestions. Either
  adjust the plan to avoid the recorded failure, or explain explicitly
  why the gotcha does not apply. Never silently proceed past a match.

Query by `type` whenever you can — a typed query never loads other
types' indexes, which is what keeps recall cheap at any history size.

## What to commit, and as which type

- **gotchas** — a VERIFIED failure: something that actually broke,
  confirmed against a real artifact (a failing build, a corrupted row, a
  measured regression). One shard per failure; put the failure class in
  `body.class` and searchable topics in `tags`. Never record suspicions,
  never record churn. Write-once; never pruned.
- **facts** — stable ground truth about the domain or operator:
  architecture, conventions, ownership, pinned versions. Rarely
  invalidated. If it changed twice this week, it is not a fact yet.
- **decisions** — a receipt for every action taken (or gated no-op):
  inputs, policy applied, action, outcome, model version. Receipts
  replace transcripts — write them structured, not as prose.
- **artifacts** — large blobs (diffs, reports, datasets), referenced by
  CID and fetched only on demand. Do not inline them into other shards.

## When a run is worth committing

Commit when the run produced something a future cold-start would need:
a new verified failure, a decision with consequences, a fact that
changed, an artifact worth citing. Do NOT commit conversational
back-and-forth, retries, or anything a future agent can re-derive
cheaply from the code itself. When gated below the value threshold,
commit the no-op receipt — the gate decision is itself history.

## Keys and tags

Keys are stable dotted paths (`gotcha.sqlite-wal`, `fact.arch.stack`)
— a re-used key shadows (the old version stays resolvable at old
roots), so re-use a key only for a genuine revision of the same thing.
Tags are the recall surface: tag with the topics a future query would
actually use.

## Proving

When a decision's legitimacy might be questioned later, attach
`memory_prove {"claim": {"type": "decisions", "key": "decision.<id>"}}`
output to your report. The proof verifies offline against the root.

## Failure discipline

If a recall reference fails to resolve or a commit fails: STOP. Report
the failure, preserve the last known-good root, and wait for a human.
Never retry into a commit from a degraded state.
