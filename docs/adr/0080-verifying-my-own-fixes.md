# ADR 0080: Verifying my own fixes

## Status
Accepted. Phase 2 round 5 — an adversarial pass whose only target was the
changes made earlier the same night. It was not dry, and one of the findings
is a reward hack **I introduced**.

## Why this round existed

ADR 0075 shipped a regression that killed `aef loop cycle` outright, caught
only by a later sweep. That is evidence about the process, not a one-off. So
the last round attacked tonight's six commits rather than a new area.

Five findings. Two maximal. The headline claim of the previous commit — *"G4
now compares base against head: a control on at the base ref and not on in
the candidate is a finding **however it was turned off**"* — was false in
three attacker-reachable ways, and it shipped with **zero tests**.

## The reward hack I introduced

ADR 0076 added `RECOVERED_KEY` so a run that recovered from a transient error
would stop being scored as an outright failure. It is written by **Zone A
code the candidate authors**, and it *relaxes* the pass predicate.

```
broken-honest              passed=False regressed=True
broken-MARKED-recovered    passed=True  regressed=False
```

Identical broken candidate. One extra dict key. A real G2 regression
disappears — and harvest stops promoting the agent's own failures into the
corpus that would later hold it to them.

`policy_denied` (ADR 0064) is safe by comparison for a reason I did not
carry across: **only `PolicyEngine` — Zone B — writes it.** `recovered` had
no such writer, so its contract was "whatever agent code says". ADR 0076's
stated safeguard, that `plan_status == "done"` is still required, does not
bind: a candidate that writes the marker also writes the plan status.

Introducing the marker is now an owner-only change, judged base-vs-head. An
agent the owner already blessed with recovery handling keeps it; a candidate
cannot start declaring its own failures recovered.

## Three evasions of the check I had just written

- **`git mv` the module and drop the control in the moved copy.** `raw_diff`
  uses `--no-renames`, so a move arrives as delete + add; the per-file loop
  skipped deletions, so the base was never read for the old path and the new
  path had no base. **The diff handed G4 exactly the evidence it needed and
  G4 discarded it.** The comparison is now made across all touched paths at
  once, which makes a move indistinguishable from an edit — which is what it
  is.
- **Add an unguarded duplicate edge.** `_resolve_route` takes the first
  matching edge by priority, so the twin wins while the guarded edge sits
  there looking reassuring. Recording only *guarded* edges could not see it:
  the diff is purely additive and removes nothing. A transition is now
  guarded only if **every** edge for it carries the control — the
  intersection, not the union.
- **Give the guarded edge a false condition and add an open twin.** Same
  dict collision, plus conditions were ignored entirely. A conditional edge
  now counts as unguarded, because it only guards the paths its condition
  admits.

Each was verified as a genuine HITL bypass through a real `GraphExecutor`
before being fixed, not merely as a scanner result.

## The false positive that halted the loop

Keying on `(from_node, to_node)` made **renaming a node while keeping the
control** a security event — and a security event halts the loop
unconditionally. A two-line rename bricked the autonomous loop with a false
accusation.

Combined with the evasions, the gate was inverted: firing on the benign
refactor, silent on three hostile ones. A removal is now reported only when
the transition **still exists** and is no longer guarded. An edge that is
gone entirely is an ordinary refactor.

## Halt criterion 4 was a lifetime counter

Its only reset was `EventKind.MERGED`, written solely on the auto-merge path
— and Tier-1 is off. So nothing reset it from the CLI. Two re-gated
proposals thirty days apart, with twenty ordinary rejections between them,
halted the loop for "working outside its evidence base". Neither was
consecutive; neither was an owner rejecting an escalation.

Escalation is the *normal* terminal state while Tier-1 is off, so the
criterion has to be about a trailing pattern or it is about nothing. It now
counts the trailing run of proposals and stops at the first that ended any
other way.

## What held up

Reported because a dry result is evidence. **The whole-tree drift arithmetic
is exact** — hand-computed against the real path: no change `0.0000`, one
line of thirty `0.0333`, a ten-line file deleted `0.3333`, a five-line file
added `0.1429`. **Halt criterion 3 cannot be tripped spuriously**; the
`DRIFT_EXHAUSTED` constant does exactly the job ADR 0077 claimed. **The
proposer's regex alignment holds** across twenty hostile inputs — `# noqa`,
comments containing `=` and `#`, escapes, emoji, CJK, `# type: ignore[...]`,
no-newline-at-EOF — zero produced invalid Python, and the comment survives
verbatim in every one.

## Left open, deliberately

`scenario_runner` still supplies no `hitl_approvals`, so a HITL-gated
incumbent still crashes and scores 0 and G2 still sees no regression. ADR
0079 named this as one of two causes and fixed only the other. It is not
fixed here either, because the honest fix is a design decision an owner
should make: supplying approvals in the gate means the gate approves things
on the owner's behalf, and the alternative — scoring a HITL pause as
something other than a failure — changes what `Outcome.passed` means. G4's
static check is now the sole defence and is, as of this ADR, tested against
six attacks and four benign cases. **That is a mitigation, not a fix, and it
is stated as one.**

Also open: `PolicyEngine()` in the gate denies every adopter tool call with
no config path to change it, so `Outcome.policy_denials` saturates on both
sides and can never differ. Harmless here (this repo's agent makes no
policy-gated call) and wrong for anyone who follows the CrewAI checklist.

## Confidence
High on what was fixed: six attacks caught, four benign cases silent, each
reproduced before and after. **Low on completeness, and that is the finding.**
Five rounds have each produced defects; the rate has not fallen; and this
round's most severe item was introduced by the round before it. The honest
read is that this codebase's failure mode is seams between correct parts, and
that a single pass over any area — including this one — is not evidence the
area is clean.
