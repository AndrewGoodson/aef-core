# ADR 0094: The candidate is not asked

## Status
Accepted. Option (b) from `MORNING_REPORT.md` §5, chosen by the owner.
Supersedes the security model of ADR 0085 and ADR 0088, both of which were
defeated.

## The problem, stated once more

Three controls were built to stop a candidate authoring the evidence that
judged it. Each was defeated, and each defeat came from a smaller change than
the last:

- **ADR 0085** framed the result channel with a per-run nonce and claimed
  three independent layers.
- **ADR 0088** found one layer false — `sys` was reachable through
  `aef.harness` — denied the import and the attribute, and said "low on
  completeness".
- **ADR 0093** found the attribute denial reads *syntax* while the
  interpreter offers the same reach by *string*: `getattr(m, "os")`,
  `vars(m)`, `m.__dict__`.

The common cause was never the specific hole. It was that **the candidate's
code and the code reporting on it shared an interpreter.** Any channel the
reporter can write, the candidate can write. Patching a denylist a fourth
time was declined.

## Decision — invert control

Separating the processes alone buys nothing: a child that reports its own
results forges them exactly as before. What works is inverting who drives.

**The parent owns the state, the routing, the step count, the trace, the
classification and the score. The child evaluates one node and returns
`(delta, route)`.**

`GraphExecutor` is untouched and does not know the difference. The only thing
that moved is where `node.fn` runs: `isolated.graph_from` rebuilds the
candidate's graph in the parent with proxy functions that RPC to a worker.
`node.fn` was always the only place candidate code executed; now it is the
only place it executes *and* the only thing it can influence.

The worker never learns what a scenario is, how many there are, what an
`Outcome` is, or whether anything passed. A test asserts that structurally,
against the AST rather than the prose.

## What this does and does not close

**Closed.** A candidate can no longer claim scenarios it never ran,
fabricate an aggregate report, print a result the harness reads, or exit
cleanly mid-run and have that read as success. Verified against every attack
in ADRs 0085/0088/0093, through the real six-gate pipeline:

```
G0: pass   (the getattr bypass is STILL invisible to static analysis)
G2: fail — 3 previously-passing scenario(s) no longer pass
```

G0 passing is the point. The attack fails because the evidence moved, not
because the scanner improved — and a test pins that, so the boundary is not
later mistaken for a static-analysis win.

Killing the worker mid-corpus now scores 1 of 3: the scenario it genuinely
ran counts, and the rest are recorded as unrun. A run that stopped is not a
run that passed.

**Open, deliberately.** A candidate can still return a lying `StateDelta` —
`plan=done` for a task it cannot do. That is the node contract, and it is
precisely the surface the corpus and the `MUST_FAIL` tripwires exist to judge
(ADR 0060). Isolation was never meant to stop it; it stops the candidate
bypassing the judgement altogether. A test pins this as a chosen boundary
rather than an oversight.

## The removed protocol

`scenario_runner`'s marker/nonce machinery is **deleted, not deprecated**. It
embodied the disproven model, and a superseded module whose docstring still
described a security property is exactly how someone wires it back. What
remains there is an in-process single-scenario helper, documented as unsafe
for scoring a candidate.

## Open items this ADR does not address

- **The worker is a plain subprocess.** `run_variant` previously received a
  `SandboxPolicy` and it is now ignored — rlimits, the scrubbed environment
  beyond `PATH`/`HOME`/`LANG`/`PYTHONPATH`, and the wall-clock timeout are
  not applied to the worker. That is a real regression in defence-in-depth
  against a *runaway* candidate, and it is stated rather than hidden. The
  containment against a *dishonest* one is what this ADR changes.
- Per-node timeouts. A node that never returns hangs the parent.
- The graph description is the candidate's declaration, like its source, and
  is judged the same way — by G0 and G4 reading the base ref.

## Confidence
High on the property: every published attack against the old channel was
re-run and none produces a passing scenario, with controls proving the honest
path still passes 3 of 3 and that a node-contract lie still can.

**Not claimed:** that this is the last word. It is the first design here
whose security argument does not depend on enumerating what a candidate
might think of — which is why it is worth more than the three that did — but
the sandbox gap above is real and should be closed before anyone calls the
worker contained.
