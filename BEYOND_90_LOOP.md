# Beyond-90 loop — where the score stops being the point

Input: `TO_90_LOOP.md` complete (90/100). Output: an independently
re-scored rubric, real signal in the corpus, and an honest statement of the
ceiling — which may be lower than 100 and may be reached before the work
runs out.

Every rule of `IMPROVE_LOOP.md` and the multi-agent protocol of
`ABOVE_90_LOOP.md` apply unchanged. HARD-STOP gates bind
(`docs/autonomy/self-improving-loop.md` §4). Read `CLAUDE.md` first.

## The problem with being at 90

**We are grading our own homework.** The rubric was written by the same
loop it scores, the weights were chosen by it, and every row cites evidence
this loop produced. That was defensible at 50, where the gaps were obvious
and the direction mattered more than the number. It is not defensible at 90,
where the remaining points are judgement calls and the incentive to read a
measurement generously is strongest.

The scoreboard has already been wrong once in a way nobody noticed for nine
increments (ADR 0127 — the total was carried by hand while nothing
recomputed it). That was arithmetic. The harder version is a dimension
scored 19/20 because the person scoring it built the thing.

So J0 comes first, and if J0 says the score is lower than 90, **that is the
score** and the rest of this loop works from there.

## J0 — an independent re-score (dim: any; ADR 0132)

**Dispatch a fresh agent with no access to `IMPROVE_LOG.md`, the ADRs, or
this loop's history.** Give it only: the rubric's weights table and
dimension definitions, the repo, and the field references (DGM, autoresearch,
ACE, WikiSkill, the self-evolving-agents survey). Ask it to score each
dimension from the code and tests alone and to write one line of evidence
per dimension naming the file that convinced it.

Then diff its scores against ours. For every dimension where it scores
lower:

- If its reasoning is right, **take the lower score** and say so in the ADR.
  A dimension talked back up is exactly what J0 exists to prevent.
- If it missed something, the evidence it missed was not discoverable from
  the code — which is its own finding, and the fix is to make it
  discoverable, not to overrule the reviewer.

Budget: one agent, no live model calls beyond its own reasoning. Deliverable:
ADR 0132 with both score sets side by side, every disagreement resolved in
writing, and the rubric updated to whichever number survived.

**Do not run the rest of this loop until J0 lands.** Every increment below
claims points on a scale J0 may move.

## J1 — Real signal, honestly bounded (dim 7: 5 → 7; ADR 0133)

Dimension 7 is worth five points and asks for "live runs and real tenants,
not a synthetic corpus". We can honestly claim two of them and not five.

**What we can do:** this repo now generates real runs of real graphs making
real model calls — I11 recorded twenty, I12/I13/I14 will make more, and
`aef run --record-runs` captures them. Point `harvest` at *those* and let
the loop learn from traffic it actually produced, redaction on (ADR 0119),
the cassette carrying the model calls (ADR 0126's fix). That is a genuine
step up from hand-written scenarios: real graphs, real failures, real
non-determinism, discovered rather than authored.

**What we cannot do without you:** a third party. "Real tenants" means
someone else's data, someone else's failure modes, and the tenant-isolation
seams (`agent_id` scoping, the keyed canary hash, redaction) meeting inputs
nobody on this side chose. Two adversarial rounds have already found tenant
scoping defects in this repo — ADR 0118's default retriever read every
tenant's records, and it was the *second* time that same widening appeared.
A loop that scores itself 10/10 on real-tenant evidence without a real
tenant would be doing the thing this whole programme is built against.

So: **+2, and the last +3 stays unclaimed** with a line in the ADR saying
what would earn it. If the owner authorises a real target, that is a new
increment with its own ADR and its own adversarial round — not a footnote
to this one.

## J2 — Make the archive earn its keep (dim 6: 8 → 10; ADR 0134)

I10 measured the LLM proposer producing four distinct candidates per run
and exactly **one kept** — and ADR 0121 measured sampling buying zero
diversity over greedy, because the rule-based proposer had one idea. Those
two facts have never been measured together: *sampling on, LLM proposer on,
enough turns to matter.*

Measure: `run_loop --proposer llm --sample-parents` against
`--proposer llm` greedy, 8+ turns each, on the summary corpus (which is the
first corpus where a candidate can fail on content rather than by raising).
Report kept count, **distinct kept trees**, the task-metric trajectory per
turn, and G5 drift consumed.

**Falsification:** if distinct-kept-trees is 1 in both arms, the archive
buys nothing even with a proposer that has a repertoire, and dim 6 does not
move — record it and consider whether `sample_parents` should be deleted
rather than left as a knob nothing justifies (ADR 0101's rule: a stub
unimplemented across five phases is a promise, and an unkept promise in a
typed signature is worse than an honest absence).

**Known obstacle, stated in advance:** I10 saw G5's 0.5 drift budget
exhausted by one ~28-line LLM diff, and two consecutive drift rejections
halt the loop. Eight turns may halt at three. If it does, that is a finding
about the drift budget under an LLM proposer, not a failed measurement —
write it up as one. Do **not** raise the budget to make the run complete;
that is weakening a control to get a number.

## J3 — Containment on by default (dim 4: 14 → 15; ADR 0135)

ADR 0105 built the contained shadow and left it opt-in. The trust case's
second load-bearing finding is that a shadow node doing direct file I/O is
not contained by the tool policy — demonstrated, and fixable exactly this
way. Make the container the default **when a runtime and image are
available**, with an explicit, logged fallback when they are not.

This strengthens a control, so it needs no owner decision — but it is
promotion-path code: reproduce the uncontained write first, keep the
fallback named and visible in the ledger, and touch neither `PolicyEngine`,
the gates, nor Tier-1. If it cannot be done without weakening something,
stop and ask (HARD-STOP gate 2).

## J4 — The two conflated signals (dim 2: 19 → 20, dim 3: 9 → 10; ADR 0136)

Both remaining points are blocked by the same shape: a rig where two things
that currently coincide come apart.

- **Dim 2** — ADR 0118 surfaced `helpful`/`harmful` but does not rank on
  them, because on every rig built so far "harmful" and "live" coincide: a
  lesson whose failure keeps recurring is exactly the one to keep showing.
  Needed: a corpus where a lesson is *harmful and resolved* — retrieved,
  and the run fails **differently** because of it. Then ranking on the
  tally can be measured against not ranking on it.
- **Dim 3** — no self-preference control exists, because nothing here has a
  judge ranking *model outputs* against each other. The LLM proposer now
  produces several candidates per turn (I10: four distinct). A judge asked
  to rank those is the first place self-preference can bite, and the first
  place it can be measured: same candidates, judged by the model that wrote
  them versus a different one.

If the rig cannot be built honestly, **leave both points unclaimed.** A
+1 taken on a rig designed to produce it is worth less than nothing.

## When to stop

This loop has a ceiling and should say so before it starts.

- **Dimension 7's last three points cannot be earned in this repo.** They
  need a third party. 97 is therefore the honest maximum for any amount of
  work done here.
- **A dimension at N-1 whose last point needs a rig built to produce it is
  finished.** Say so and move on.
- **If J0 lowers the score, the lower number stands** and this loop's
  target moves with it.
- When the remaining increments are all "build a rig that would let us
  claim the point", the loop is done and the honest output is a report
  saying which points are unreachable and why — not more increments.

The number was a useful instrument for getting from 50 to 90 because the
gaps were real and the direction was obvious. Past 90 it starts measuring
the scorer. Run the adversarial round, publish the ceiling, and stop.

## After each merge wave

Seam-hunt the diff. Eight for eight so far — every adversarial round in
this programme has found a defect, and the last one found ten including two
that made previously-shipped ADR claims false. Assume this one will too.

## Report

`docs/research/beyond-90-<date>.md`: J0's independent scores beside ours
with every disagreement resolved, each increment's measurement and
falsification, the points deliberately left unclaimed, and the ceiling.
