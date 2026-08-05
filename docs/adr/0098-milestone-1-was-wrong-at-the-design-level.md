# ADR 0098: Milestone 1 was wrong at the design level

## Status
Accepted. **Reverts the transformation shipped in ADR 0096 and the executor
change in ADR 0097.** Both remain in the index as the record of a decision
that was made and withdrawn.

## What happened

ADR 0096 chose `add_deterministic_fallback` as the first structural
transformation, and justified it in part with:

> It is **already verified**: ADR 0068 made replay check that a recorded
> fallback route still matches the declared one.

That sentence is true and it answered the wrong question. I checked whether a
fallback is *verified*. I never checked whether an agent is *permitted to
declare one*.

**It is not.** `fallback_node_id` has been in G4's `OWNER_ONLY_FIELDS` since
ADR 0036/0039, with a stated reason: an agent-declared fallback swallows
errors and makes replay trust the record instead of verifying it. Reproduced
through the real six-gate pipeline on the cleanest possible instance — a
two-token diff, handler already declared by the incumbent:

```
G0: pass   1 file(s), 2 line(s), all Zone A, no static-safety violations
G1: pass
G4: fail   1 owner-only safety declaration(s) in agent-authored code
DISPOSITION: reject
```

**Milestone 1 shipped a proposer whose only structural output is the one
thing the gate set explicitly forbids** — and `_structural` returned it in
*preference* to the numeric proposal G4 passes. So the loop would have
flipped from emitting mergeable candidates to emitting only security events,
the moment one new reflect record existed.

## Why the tests did not catch it

`test_gates.py` asserts G4 flags `fallback_node_id`. `test_structural_proposer.py`
asserts the transformation produces it. Both correct; neither ran a proposal
through a gate.

The acceptance test — the one I wrote specifically to demand a *repair*
rather than a *diff* — called a bare `GraphExecutor`. It proved the fix
works and was structurally incapable of seeing that the pipeline rejects it.

I wrote in ADR 0097 that acceptance tests must demand a repair. That was
right and insufficient: **an acceptance test must run the thing the system
would actually run.** Mine stopped one layer short of the gates, which is
exactly the criticism ADR 0079 made of a fixture that hand-repaired its own
preconditions.

## Three further findings, each independently disqualifying

**The recovery marker was ADR 0080's hack relocated.** ADR 0097 had the
executor set `recovered` when a fallback fired. Zone B authorship makes the
marker unforgeable; it does not make it *meaningful*. Reproduced: an
identical genuine regression fails G2 without a fallback and **passes with
one** — a fallback to a node that returns `done` doing no real work converts
a broken candidate into a clean one. Word for word ADR 0080's finding, on a
different two-token declaration.

**Only half of ADR 0097 shipped.** `Outcome.passed` honours recovery;
`RuleBasedEvaluator.task_completion` does not, and that is what G3 scores.
A working fallback passes G2 and scores **0.0** in G3 — identical to giving
up. Three consumers of "did this fail", two behaviours.

**The handler choice livelocks.** `_handler_candidates` returned every
declared node and `_structural` took the first that applied. In a normally
ordered agent the first declared node is the *entry* node, so
`fetch → plan → fetch` — reproduced as `GraphExecutionError: exceeded
max_steps=1000`, per scenario, times the corpus, times five cohort members.

## Decision

Reverted: the transformation, the proposer's structural preference, and the
executor's recovery marker.

Kept, because each stands on its own:

- **The reflect node records `failing_nodes`.** The failing node's identity
  was being read and discarded; recording it is correct regardless of what a
  proposer later does with it.
- **`MemoryEvidence.failing_nodes()`** pairs a node with the record naming
  it, so a future citation can constrain its target.
- **`RECOVERED_KEY` in `aef/state/schema.py`.** The kernel must not import
  the harness, and that layering is right whoever sets the marker.

## What a correct Milestone 1 requires

Not a different transformation — a prior question answered first: **what may
an agent-authored change legitimately contain?** G4's `OWNER_ONLY_FIELDS` is
the existing answer, and the catalogue must be drawn from what remains after
it, not proposed and then checked against it.

That question is the owner's, because it is the same question as "what may
the loop change without me". Three candidate answers, none of which I should
pick alone: extend the catalogue to changes G4 already permits; make certain
owner-only fields proposable-with-escalation rather than forbidden; or accept
that the numeric proposer is the honest ceiling until the gate set says
otherwise.

## Confidence
High on the revert: every finding was reproduced by running, and the headline
was reproduced through the real pipeline rather than a component. **On my own
judgement, low.** I designed a transformation against a constraint I had not
read, wrote an ADR asserting it was "already verified", and shipped it behind
sixteen passing tests. That is the third time in this program an ADR has
carried a claim I had not actually checked — ADR 0088 and ADR 0093 are the
others, and the pattern is the same each time: a true statement about one
property, presented as an answer about a different one.
