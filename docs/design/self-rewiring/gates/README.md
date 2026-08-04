> **⚠ REVISED — read `04-review-and-self-coding-redesign.md` first.** Three-reviewer
> audit disproved this document's premise (edges authorize routes; nodes choose them)
> and found the gate pipeline admitted only no-ops. Scope is now self-coding with a
> structurally isolated harness (ADR 0044). Retained for provenance.

# The gate pipeline

Ordered, fail-fast. A candidate must pass **every** gate to be surfaced to
the owner. A candidate failing any gate is auto-rejected, logged with the
reason, and **never reaches the owner** — this is what stops the human gate
from degrading into a rubber stamp.

| # | Gate | Cost | Rejects |
|---|---|---|---|
| [G0](G0-palette-and-scope.md) | Palette + scope | trivial | Refs outside the palette; edits to owner-only fields |
| [G1](G1-loads-and-compiles.md) | Loads + compiles | cheap | Manifests that don't resolve or don't `validate()` |
| [G2](G2-golden-scenario-reexecution.md) | Golden-scenario re-execution | **expensive** | Behavioural regression on any golden scenario |
| [G3](G3-eval-non-regression.md) | Eval non-regression | moderate | Candidates scoring worse than the incumbent |
| [G4](G4-separation-of-powers.md) | Separation of powers | trivial | Any proposal touching its own suite or corpus |
| [G5](G5-rate-and-drift.md) | Rate + drift budget | trivial | Too-frequent changes; accumulated sub-threshold drift |

**Ordering rationale.** G0/G1/G4 are near-free and reject the majority of
malformed or out-of-bounds proposals, so they run before the expensive
corpus re-execution in G2. G4 is deliberately early: a proposal that tries
to edit its own tests is rejected before it gets to run them.

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
