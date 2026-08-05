# ADR 0099: A catalogue derived from the gates

## Status
Accepted. Supersedes ADR 0096's catalogue. Milestone 1, second attempt.

## The prior question, answered first

ADR 0098 ended by saying a correct Milestone 1 needs a prior question
answered: **what may an agent-authored change legitimately contain?** Rather
than answer it from argument, the six candidate transformations were run
through the real G4 on the cleanest instance of each:

```
PASS  T1 retry loop inside a node body
PASS  T2 add a reflect node + route to it
PASS  T3 widen a routing condition
PASS  T4 split a node into two
PASS  T5 numeric constant (today's proposer — control)
FAIL  T6 fallback_node_id (ADR 0096's transformation — control)
```

`fallback_node_id` was **the only forbidden one**. ADR 0098 recorded the
option as "safest, probably not much left"; that was a guess, and the measured
answer is the opposite — the catalogue was one item away from being entirely
legal. A second probe checked whether the prohibition binds on a NEW node as
well as a modified one, since a fresh declaration has no base-ref counterpart
to be weakened against:

```
FAIL  N1 NEW node: fallback_node_id
FAIL  N2 NEW node: deterministic=True on an io node
PASS  N3 NEW node: plain deterministic=True on a pure node
FAIL  N4 NEW EDGE: requires_human_approval=False
```

`scan_metadata` is whole-file, not base-vs-head. There was no hole. Recorded
because the suspicion was raised in writing and would otherwise stand.

## Decision

**The catalogue reads its constraint from the gate.**
`_assert_controls_untouched` imports `OWNER_ONLY_FIELDS` from
`g4_separation` and compares the before-signature against the after-signature
of every `Node(...)` and `Edge(...)` in the file. Adding a field to that
frozenset automatically forbids the catalogue from emitting it; nobody has to
remember. Verified by planting each of the six fields **from its real name** —
all six caught, and a benign edit does not trip it.

The first entry is `add_bounded_retry`: wrap a flaky node's function body in a
bounded retry loop. It replaces `add_deterministic_fallback` on the
distinction ADR 0080 and ADR 0098 both turned on — **a fallback records that
control continued; a retry means the work happened.** The acceptance test
asserts the repaired run sets the flag that only the failing node sets, so
"it recovered" cannot be satisfied by a handler that does nothing.

The retry emits `RETRY_ATTEMPTS` as a module-level constant in the agent's
source rather than inlining `3`, so the structural change creates a knob the
existing numeric proposer can then tune under the same gates.

Preconditions are refusals, never guesses: `deterministic=False` (a
deterministic node raises identically on every attempt), a body ending in
`return` (otherwise a fall-through would silently run N times), no existing
retry, a module-level function to rewrite, and the two below.

## What the adversarial round found

**A2, reproduced: a side effect executed three times before the failure
surfaced.** No gate can see this — G2 and G3 measure outcomes and nothing in
the corpus counts side effects. The node contract's answer is
`idempotency_key_fn`: the executor computes the key once per node execution,
so every attempt carries the same key and a deduplicating consumer collapses
them (ADR 0010). So the transformation now **requires** that declaration for
any non-pure node and **refuses MUTATING outright**, where "the consumer
dedupes" is not a premise to rest an unattended merge on. Both spellings —
`SideEffect.MUTATING` and `"mutating"` — verified to bind.

**A1, reproduced and worse: `except Exception` swallowed an approval
requirement.** A node raising `HumanApprovalRequiredError` on one attempt and
returning normally on another had the requirement absorbed, turning a HITL
gate into a silent pass — HARD-STOP #7 exactly.

The first fix emitted `except HumanApprovalRequiredError: raise` into the
agent source, **and G4 rejected it**: introducing that class into
agent-authored code is a security event in its own right ("whether a run
stopped at a human-approval gate is the kernel's finding to report, not the
candidate's to assert"). That is ADR 0098's mistake in miniature — a fix
designed against a constraint I had not read — caught this time because the
gate was run rather than reasoned about, one working session after the same
error cost a whole milestone.

The shipped answer is a **refusal**, not emitted code, and it asks the
question using G4's own `_raises_approval_required`. In the normal path the
executor raises approval *after* `fn` returns, where no retry can reach it;
the only exposure is agent code raising it directly, which is what the
precondition detects. **Residual risk, stated rather than papered over:** a
node raising it from a helper in another module is not visible to this check.

`SystemExit` and `KeyboardInterrupt` are `BaseException` and were confirmed
uncaught. A lambda-bound node is refused.

## The acceptance test

Runs `gate()` and then `cycle()` — not a bare `GraphExecutor`. ADR 0098's
finding was that an acceptance test must run **what the system would actually
run**, and its predecessor stopped one layer short of the gates. This one
plants a flaky node in a real git repo, **records the corpus by running the
agent** while the dependency is healthy, has the reflect node write the
failure memory, and drives the real `cycle()` — which proposes, materialises a
branch, and gates it. Every gate executes; none rejects.

Two controls make the assertion falsifiable, both of which the previous
acceptance test would have failed:

- a candidate carrying `fallback_node_id`, planted from the real declaration,
  must be REJECTED by G4 with `Disposition.REJECT`
- `_assert_controls_untouched` must fire for every field in
  `OWNER_ONLY_FIELDS` and not for a benign edit

## Confidence
Moderate. The catalogue has one entry, and one entry chosen because it is the
only candidate that both passes the gates and demonstrably repairs something.
T2 and T4 pass G4 but repair nothing measurable, and shipping a transformation
with no demonstrable effect is the defect class ADR 0092 named — a declared
injection point that reads as a present feature. They are deliberately not
shipped.

Two of this round's findings were in code I had written hours earlier and
believed correct, and one of those was a fix for the other. The adversarial
round is doing the work; my first drafts are not.
