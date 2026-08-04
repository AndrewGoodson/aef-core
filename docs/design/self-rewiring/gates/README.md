> **⚠ REVISED — read `04-review-and-self-coding-redesign.md` first.** Three-reviewer
> audit disproved this document's premise (edges authorize routes; nodes choose them)
> and found the gate pipeline admitted only no-ops. Scope is now self-coding with a
> structurally isolated harness (ADR 0044). Retained for provenance.

# The gate pipeline

Ordered, fail-fast. A candidate must pass **every** gate to be surfaced to
the owner. A candidate failing any gate is auto-rejected, logged with the
reason, and **never reaches the owner** — this is what stops the human gate
from degrading into a rubber stamp.

**Canonical execution order — `G0 → G1 → G4 → G5 → G2 → G3`** (04 §2.4).
The table below lists gates by *identifier*, not by run order; the
`01-architecture.md` mermaid diagram showing `G0→G1→G2→G3→G4→G5` is
**wrong** and is corrected there.

| # | Gate | Cost | Runs | Rejects |
|---|---|---|---|---|
| [G0](G0-palette-and-scope.md) | Zone + static safety | trivial | 1st | Diffs outside Zone A; edits to owner-only fields; over-budget diffs |
| [G1](G1-loads-and-compiles.md) | Builds | cheap | 2nd | Doesn't resolve, `validate()`, type-check, or pass the existing suite |
| [G2](G2-golden-scenario-reexecution.md) | Outcome non-regression | **expensive** | 5th | A previously-*passing* scenario that no longer passes |
| [G3](G3-eval-non-regression.md) | Improvement on held-out | moderate | 6th | Candidates not beating the null-hypothesis control cohort |
| [G4](G4-separation-of-powers.md) | Separation of powers | trivial | 3rd | Any proposal reaching its own suite, corpus, or gate code |
| [G5](G5-rate-and-drift.md) | Rate + drift budget | trivial | 4th | Too-frequent changes; accumulated sub-threshold drift |

**Ordering rationale.** The four near-free gates (G0, G1, G4, G5) reject
the majority of malformed or out-of-bounds proposals, so all of them run
before the expensive corpus re-execution in G2. G4 is deliberately early: a
proposal that tries to edit its own tests is rejected before it gets to run
them. G5 precedes G2 for the same cost reason — a candidate over its drift
budget is rejected without paying for a corpus run.

**Determinism requirement.** Every gate is control-plane and must be
deterministic — a candidate's acceptance never depends on a model call.
The proposer may be non-deterministic; the judgement of it may not.

**Shared failure semantics.** Every gate returns a structured result
(`pass|fail`, reason, evidence). Nothing is auto-applied on pass; the
candidate simply advances. Nothing needs rolling back on fail, because
**no change has been applied at any point in the pipeline** — the pipeline
evaluates a *proposed* manifest against a *candidate* graph constructed in
memory. Rollback (`G_archive`) only concerns changes that were merged, and
is covered in `../01-architecture.md` §4.5.
