# ADR 0050: G2 compares outcome classes, not execution paths

## Status
Accepted. Implements M4. Supersedes the G2 specification in
`docs/design/self-rewiring/gates/G2-golden-scenario-reexecution.md`.

## Context
The superseded G2 spec compared the candidate's **execution path** against
the recorded one and rejected any divergence. Its headline test was
"flipping an edge priority so routing changes ⇒ gate fails", described as
"the proof that the gate does what replay could not".

Two reviewers found the same consequence independently: **every non-trivial
change alters the path**, so that pipeline could only ever admit no-ops. It
read as the strictest possible gate and was in fact vacuous — the one
failure mode worse than a weak gate, because it produces confident-looking
green results while approving nothing of substance.

## Decision

**1. G2 compares outcome classes.** An `Outcome` is `(terminated,
plan_status, error_count, policy_denials, node_path)`. The comparison uses
the first four; `node_path` is carried for reporting only. A candidate may
reach the same outcome by a different route — that is what an improvement
usually *is*.

**2. Routing divergence is reported, never rejected.** It is genuinely
informative to a human reading the report, and it is not evidence of harm.
The `Comparison.summary` for a diverged-but-equivalent scenario says so
explicitly, so a reader is not left guessing why it did not fail.

**3. Only previously-passing scenarios are held.** A scenario the incumbent
already failed may change freely: the incumbent has no claim on behaviour it
never got right. This asymmetry is what makes the rule both sound and
non-vacuous — it holds exactly the behaviour that currently works.

**4. A new policy denial is a regression even when the plan still
completes.** `PolicyEngine` is deny-by-default (constraint #6); a candidate
that starts tripping a gate the incumbent cleared has changed behaviour that
matters, whatever the plan status says.

**5. An empty corpus FAILS.** Absence of evidence is not evidence of
non-regression. A gate with nothing to check must escalate (ADR 0045
condition 7), never quietly pass. The same applies to a scenario that
produced no outcome under the candidate: silently skipping it is how a
corpus stops binding.

**6. The incumbent's outcome is derived from the recorded trace, not
stored.** A scenario file records what *happened*; deriving the
classification means a change to the classification rule re-classifies the
whole corpus consistently, rather than leaving old entries judged by an old
rule.

**7. The holdout split is not spent on routine gate runs.** G2 gates against
`train` and `validation` only.

## Consequences
- The candidate's graph is loaded and executed **inside the sandbox, in the
  post-merge workspace**, whose `aef/` comes from the base ref (ADR 0047).
  The runner executing agent code is therefore the harness's own; the
  candidate supplies only a `Graph`.
- The runner records a scenario that raises as a non-terminating outcome
  rather than aborting the batch — one broken scenario is a result about
  that scenario, and losing the other ninety-nine to it would hide more
  than it reveals.
- An agent-authored `build_graph()` that raises surfaces as an
  `EntrypointError`, not as an unhandled traceback. Found by a test, not
  anticipated.
- 29 tests. The two acceptance cases are stated directly: a routing-only
  change **passes**, and breaking a previously-passing scenario **fails**.
- **Weaker than the spec it replaces in one respect, stated plainly:** a
  candidate that reaches the same outcome via a materially worse route —
  more model calls, more cost, a longer path — is not rejected by G2. Cost
  and quality are G3's remit. G2 reports the divergence so it is at least
  visible.

## Alternatives Considered
- **Keep path identity.** Rejected: it admits only no-ops, which was the
  finding that triggered this ADR.
- **Path identity with a hand-maintained allowlist of "acceptable"
  divergences.** Rejected: the allowlist becomes the real gate, it is
  maintained by whoever is trying to land changes, and it grows
  monotonically.
- **Compare final `AEFState` in full.** Rejected: too strict in a different
  direction — any timestamp, provenance entry, or working-memory key
  differs, so it degenerates into path identity with extra steps.
- **Treat routing divergence as a warning that fails after N occurrences.**
  Rejected for v1: the threshold would be arbitrary and would reintroduce
  "changing behaviour is suspicious" as a rejection criterion by the back
  door. Drift is G5's job, measured deliberately.

## Confidence
High on the comparison semantics — every rule has a direct test, including
the asymmetry and the empty-corpus refusal. Medium on the outcome fields
being *sufficient*: `plan_status`, error count, and policy denials capture
the failures this codebase can currently observe, but an agent could plainly
degrade quality without touching any of them. That gap is real and is why
G3 (M5) is not optional. Medium-low on the policy-denial detector, which
matches error text against substrings (`"policy"`, `"denied"`, …) rather
than a structured field — `AEFState.errors` is `list[dict[str, Any]]` with
no schema, so there is nothing better to key on today. A typed policy-denial
error entry would make this exact; it is a kernel change and is **not**
made here.
