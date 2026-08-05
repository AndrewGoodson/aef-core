# ADR 0089: Two corrections to yesterday's decisions

## Status
Accepted. Both findings come from the same adversarial round as ADR 0088, and
both are defects in decisions I made earlier in this run rather than
pre-existing ones.

## 1. The `gate_added` exemption was a free pass

ADR 0081 made `pass -> pause` **not** a regression, reasoning: *"a loop that
cannot make itself more conservative is a loop pointed the wrong way."*

That reasoning is fine and the conclusion was wrong, because a paused
scenario scores **0.0 — exactly like a failed one**. So:

```
pass -> fail    regressed=True
pass -> pause   regressed=False    <- same score, opposite verdict
```

A candidate that broke five previously-passing scenarios and added
`requires_human_approval=True` to its exit edge converted **every** regression
into a G2 PASS, at no cost. Reproduced through the real gate pipeline: G2
went from *"5 previously-passing scenario(s) no longer pass"* to *"11
scenario(s) re-executed; every previously-passing one still passes."*

G3's per-scenario score floor caught it, which is defence in depth working and
worth saying plainly. But G2 was fully neutralised, and G4 did not fire —
`scan_metadata` flags *clearing* `requires_human_approval`, never *setting*
it, and setting it is the legitimate way to add a control.

**A recorded scenario that no longer completes is a regression whatever
stopped it.** `gate_added` still reports the distinction, because "it now
waits for you" and "it broke" are different facts an owner needs to tell
apart — they just carry the same verdict. The owner approves an added control
by re-recording the scenario with the approval granted, deliberately, which
is the point of the control.

The exemption also had an exploitable asymmetry `expected="must_pass"` would
have closed — and `aef loop record --expected` defaults to `unspecified`, so
an adopter's default-recorded corpus had no protection at all.

## 2. Deep purity made legal state fatal

ADR 0087 made `StateDelta.apply` deeply pure with a bare `deepcopy`. A
`threading.Lock`, an open file, or a client handle parked in `working_memory`
went from legal to **raising `TypeError`** — and `AEFState`'s own docstring
names that field as where per-agent data belongs. Confirmed against a
worktree at the pre-change commit: it worked before.

Worse, inside `scenario_runner` the raise is swallowed by `except Exception`
and becomes 0.0 for every scenario — for candidate, incumbent and all five
cohort members alike. That is the ADR 0075 / ADR 0079 shape for the third
time: a service or capability the gate runner lacks, turning into a uniform
zero that makes G3 reject everything.

Now: deep-copy where possible, share where it is not. A value that cannot be
deep-copied cannot be checkpointed either, so the fallback loses a guarantee
that was never available for it. Deep purity for ordinary data is asserted by
its own test, so the fallback cannot quietly become the normal path.

## Cost, which ADR 0087 did not state

Measured: `apply` deep-copies the merged payloads and the executor snapshots
the state again, so roughly `0.28 ms` per super-step at 100 `working_memory`
keys, `2.5 ms` at 1000, `27 ms` at 10 000. A run is now O(nodes × |state|),
and G3 costs N+2 corpus passes, so it multiplies through the most expensive
gate. Correct, and not free — an owner with large working memory should know.

## Confidence
High: both were reproduced before the fix and re-run after, and the two tests
that pinned the exploitable behaviour were rewritten rather than deleted, with
the reasoning recorded in them. **Not claimed:** that the `hitl_paused`
semantics are now settled. This is the second revision in two days; the first
was reasoned from a principle and got the sign wrong. What is settled is the
property — pausing must never score better than failing — not the design
around it.
