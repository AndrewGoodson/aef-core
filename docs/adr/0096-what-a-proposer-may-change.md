# ADR 0096: What a proposer may change

## Status
Accepted. Design for Milestone 1 — written before the code, as the program
requires.

## Context

`RuleBasedProposer` rewrites module-level numeric constants. That is real
learning and it is one axis: the agent can discover a better retry budget, and
can never discover that it needs a retry at all.

Six gates, a control cohort, a tripwire corpus and a signed audit trail are
built to judge changes far larger than the one thing that can currently be
proposed. The judging apparatus is not the bottleneck.

## The finding that shapes the design

**The failure memory does not record which node failed.** Reproduced:

```
node_id          = reflect          <- the node that OBSERVED the failure
grounded_in      = ['errors[0]']
verbal_feedback  = 1 error(s) recorded; ... errors[0]: gave up: difficulty 9 ...
```

`ctx.node_id` inside the reflect node is `"reflect"`. The failing node's id
sits in `state.errors[0]["node_id"]`, which the reflect node reads to build
`verbal_feedback` and then discards.

A numeric proposer never needed it — it mutates whatever constants a file
happens to contain. A structural proposer cannot begin without it: "add a
fallback to the flaky node" requires knowing which node was flaky. So the
first change is to the reflection wire, not the proposer.

This is the same class as ADR 0092's finding: the information existed, and
nothing carried it to the place that needed it.

## Decision — a bounded catalogue, not code generation

A proposer may apply **named transformations from a fixed catalogue**. It may
not emit arbitrary code. Four properties are non-negotiable, and each exists
because of a specific defect this program already found:

1. **Every proposal is a diff a human can read.** G0 sizes it; a
   transformation that produces a large or unreviewable diff is rejected by
   the gate that already exists.
2. **Every proposal names the memory record that motivated it, and the
   citation is checkable.** Today's rationale reads *"grounded in recorded
   failures"* while the mutation is independent of what the failure said —
   found in a round-5 sweep and recorded unfixed. A citation that does not
   constrain the change is decoration.
3. **A transformation is individually revertible.** One named operation, one
   coherent change, so a rollback is a rollback and not an archaeology
   exercise.
4. **No transformation may alter routing into a HITL-gated edge.** ADR 0089
   measured what that buys an attacker: a candidate that broke five scenarios
   and added `requires_human_approval=True` to its exit edge converted every
   regression into a G2 pass. A proposer that can touch approval routing is a
   proposer that can launder its own failures.

## The catalogue, v1: one transformation

**`add_deterministic_fallback`** — a node that failure memory shows *raising*
gets a `fallback_node_id` pointing at an existing handler.

Chosen first because it is the only candidate that satisfies all four
properties without inventing anything:

- It is **AEF-native**: `fallback_node_id` is already in the `Node` contract,
  and `Edge.requires_deterministic_fallback` already exists to demand it.
- It is **structural**: routing changes, not a number.
- It is **directly traceable**: the memory says node X raised; the change adds
  a fallback to node X. The citation constrains the target.
- It is **already verified**: ADR 0068 made replay check that a recorded
  fallback route still matches the declared one, so a candidate cannot
  quietly re-point it later.
- The diff is **two tokens**.

**The target must already exist.** v1 does not invent a handler node. A
proposer that writes new node bodies is code generation with extra steps, and
nothing in the current gate set judges whether an invented handler is
*correct* — only whether the corpus still passes, which an empty handler
would also achieve.

## Deliberately not in v1, and why

- **Split a node whose trace shows it doing two things.** No test for
  "correctly split"; the gates would pass a split that silently drops half
  the work.
- **Widen or narrow a routing condition.** Conditions are arbitrary
  callables; a bounded transformation over them is not obviously definable,
  and this is the axis nearest the HITL-gate hazard in property 4.
- **Add a reflect node where none routes.** That is adoption tooling —
  `aef loop doctor` already reports it — not something an agent learns from
  its own failures.

Each of these can enter the catalogue when there is a gate that can tell a
good instance from a bad one. Adding them sooner would mean shipping
transformations whose correctness nothing checks, which is how a proposer
comes to look more capable than it is.

## Consequences
- The reflect node records the failing node ids. That is a memory-content
  change; records written before it lack the field and the proposer must
  treat its absence as "no structural proposal available", not as an error.
- The numeric proposer stays. It is the fallback when no structural
  transformation applies, and it is what the control cohort mutates.

## Confidence
High on the constraint set: each of the four properties is traceable to a
defect that actually occurred here. **Not claimed:** that one transformation
makes the proposer capable. It makes it *structural*, which is a different
and smaller claim, and the honest measure is whether it repairs a planted
failure end to end — which Milestone 1's acceptance test demands and which
may yet fail.
