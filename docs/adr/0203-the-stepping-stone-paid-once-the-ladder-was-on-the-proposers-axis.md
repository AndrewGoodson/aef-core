# ADR 0203: The stepping stone paid, once the ladder was on the proposer's axis

## Status

Accepted. Worker **P4** of `TO_95_LOOP.md`; record in `IMPROVE_LOG.md`.
**Rubric dimension 6 moves 8 → 10.**

The sentence three previous ADRs could not write, and the one this increment
exists for:

> **A kept candidate descends from a candidate the gates rejected.** Eight of
> ten seeded sampling runs; zero of ten greedy runs, and greedy provably
> cannot.

`sample_parents` is **not deleted**, and the reason has changed from "it might
pay one day" to "it was measured paying, under a stated condition".

## Model and budget

**Zero live calls.** The ladder corpus records no model calls, the rule-based
proposer makes none, and `ClaudeCodeProvider.complete` was wrapped by a counter
whose cap was 0 for every run — so the arms are asserted free rather than
believed free. P4's allowance was 30; 0 were spent, and no quota preflight was
needed because nothing was ever going to be called.

Pre-registration: `docs/research/j2c/prereg.txt`, written **after** the
staircase probe (which is the artifact that had to come first) and **before**
the seeded arms.

## Context — the exact reason ADR 0198 measured zero

ADR 0198 got `stepping_stone_keeps = 0` with a denominator of 5: sampling
proposed from a rejected member five times, three generations deep, and every
descendant was rejected. Its diagnosis named the missing half:

> a rig in which a rejected candidate is on the path to a kept one *and* the
> proposer can take the second step. This rig had the first and not the second.

And it said why, mechanically:

> `cycle` takes `proposals[0]`, `find_constants` returns `RETRY_BUDGET` first,
> so from **any** parent the rule-based proposal raises `RETRY_BUDGET` and
> never `QUALITY_THRESHOLD`. […] Parent diversity is worth nothing when the
> proposer's output is a deterministic function of the parent.

That last sentence is true and was read here as a dead end for two nights of
this programme. It is not one. It says the proposer walks **one axis,
deterministically** — and `agents/demo`'s ladder is on a *different* axis,
because it was built two-dimensional so the one-constant control cohort could
not match a coherent pair.

**So the fix is not a better proposer. It is a ladder on the axis the proposer
already walks.**

## The fixture, and the trade it makes

`agents/ladder/graph.py` — a new Zone A fixture, added rather than editing
`agents/demo`, because the demo's two-constant shape is load-bearing for ADR
0198's measurement and for its own docstring's argument, and a rig that
rewrites the rig it is being compared against is not a comparison.

Four module constants, `BATCH_SIZE` first in the file (which is what makes it
`proposals[0]`'s target), and a pass predicate with a floor and a ceiling: a
batch smaller than the item count cannot complete the work, and a batch larger
than the transport's five-slot frame cannot be sent at all. The ceiling is a
literal computed in the function body, not a module constant, so neither the
proposer nor the cohort can tune it.

**The trade, stated because it is the thing a sceptical reader should push
on:** `agents/demo` beats the null cohort by requiring *coherence across two
constants*, which one random single-constant mutation cannot match. This
fixture cannot use that, because the proposer cannot produce it. It beats the
cohort by making the target **narrow** instead — the winning value is a single
integer with a catastrophe immediately above it — so a random mutation has to
land exactly on it. That is a weaker guarantee than coherence and it is
deliberate: it leaves the null hypothesis able to reject, which is why the
pre-registration names it as a source of chance rather than as a property of
the design.

## 1. The staircase, measured and published before any arm ran

`run_j2c.py --probe`, read off `aef loop score` on the committed ladder
corpus, `docs/research/j2c/staircase.txt`:

| `BATCH_SIZE` | task metric | what it is |
|---|---|---|
| 1 | 0.1111 | too small for almost everything |
| 2 | 0.3333 | |
| **3** | **0.5556** | the blessed baseline |
| **4** | **0.5556** | **exactly the baseline — a step that gains nothing** |
| **5** | **0.7778** | **the rung: both `hard-5` scenarios complete** |
| 6 | 0.0000 | over the five-slot transport frame; everything fails |
| 7 | 0.0000 | |

`coerce_value` moves an integer by +25%, at least +1, so the proposal from 3
is 4 and the proposal from 4 is 5. Therefore:

- **greedy proposes from the kept branch, which stays at 3.** It proposes 4,
  G3 rejects it for not beating the cohort, and next turn it proposes 4 again
  — the same tree — and `run_loop` stops on the duplicate-rejected-tree rule.
  Greedy cannot reach 5 on any seed. This is a proof, not a probability.
- **The rung at 5 is reachable only by proposing FROM the rejected 4.**

That is a stepping stone by construction, on the axis the proposer walks, with
the second step inside the proposer's reach. ADR 0198's two halves, in one
fixture.

`PYTHONDONTWRITEBYTECODE` is set in the probe, inheriting ADR 0198's defect:
`BATCH_SIZE = 3` and `BATCH_SIZE = 4` are the same number of bytes and CPython
invalidates a `.pyc` on mtime-in-seconds plus size, so rewriting the file
inside one second silently re-runs the previous variant's bytecode.

## 2. The measurement

Two arms, identical but for `sample_parents`, over a fresh clone and fresh
state each, `rule_based` proposer, 6 turns, **seeds 0–9, every one reported.**

| arm | runs | kept | descendants of a rejected member | **kept from one** | reached rung 5 | live calls |
|---|---|---|---|---|---|---|
| greedy | 10 | 0 | 0 | **0** | 0 | 0 |
| sampling | 10 | 8 | 8 | **8** | 8 | 0 |

Per seed, with the rungs read off each candidate branch rather than inferred
from the turn number:

| arm | seed | turns | kept | parents | from a reject | **kept from one** | rungs |
|---|---|---|---|---|---|---|---|
| greedy | 0–9 | 2 | 0 | 1 | 0 | **0** | 4,4 |
| sampling | 0 | 4 | 1 | 3 | 1 | **1** | 4,5,6,4 |
| sampling | 1 | 4 | 1 | 3 | 1 | **1** | 4,5,6,4 |
| sampling | 2 | 3 | 1 | 2 | 1 | **1** | 4,5,4 |
| sampling | 3 | 5 | 1 | 3 | 1 | **1** | 4,5,5,6,6 |
| sampling | 4 | 2 | 0 | 1 | 0 | **0** | 4,4 |
| sampling | 5 | 4 | 1 | 3 | 1 | **1** | 4,5,6,6 |
| sampling | 6 | 4 | 1 | 3 | 1 | **1** | 4,5,6,4 |
| sampling | 7 | 2 | 0 | 1 | 0 | **0** | 4,4 |
| sampling | 8 | 3 | 1 | 2 | 1 | **1** | 4,5,4 |
| sampling | 9 | 3 | 1 | 2 | 1 | **1** | 4,5,4 |

Every greedy seed is identical, which is the point: greedy's parent is the
kept ref, the kept ref never moves, and the proposer is deterministic.

The eight keepers are all the same shape, read from the persisted lineage
through `archive.fold_lineage` — the fold the driver and `aef loop lineage
list` share:

```
sampling/seed0: 217598ff58af (score 0.7778) from dac3693f85b5 (score 0.5556, reject)
sampling/seed1: 9595d9e1d223 (score 0.7778) from ad1f46635c18 (score 0.5556, reject)
sampling/seed2: e47f3d0ad9bd (score 0.7778) from 6effd11a635c (score 0.5556, reject)
sampling/seed3: bd4f73d220ea (score 0.7778) from 6fa7e006e591 (score 0.5556, reject)
sampling/seed5: 4c472532f655 (score 0.7778) from f44b122e8ed4 (score 0.5556, reject)
sampling/seed6: a91b4ad2e444 (score 0.7778) from 8805ec2335cc (score 0.5556, reject)
sampling/seed8: 8da58b2ee1dc (score 0.7778) from 499cc3bc303e (score 0.5556, reject)
sampling/seed9: c8a8b91bc707 (score 0.7778) from 230d8d101d92 (score 0.5556, reject)
```

`0.7778` and `0.5556` are the probe's own numbers for rungs 5 and 4, so the
keeper is the rung the staircase predicted and not a keep for some other
reason — the third clause of the pre-registered falsification, there precisely
so a lucky keep could not be counted as a climb.

One turn of `sampling/seed0`, in the loop's own words:

```
turn 1  BATCH_SIZE=4  score=0.5556  incumbent=0.5556  reject
        G3 rejected it: candidate does not beat the p95 of the random control
        cohort — this is the null hypothesis, not an improvement
turn 2  BATCH_SIZE=5  score=0.7778  incumbent=0.5556  escalate
        every gate passed, but Tier-1 auto-merge is not enabled
turn 3  BATCH_SIZE=6  score=0.0000  incumbent=0.7778  reject
        G2 rejected it: 5 previously-passing scenario(s) no longer pass
turn 4  BATCH_SIZE=4  score=0.5556  incumbent=0.5556  reject   -> stop
```

Turn 3 is worth reading beside turn 2: the loop climbs one rung and then walks
straight off the cliff above it, and **G2's zero-tolerance regression rule
catches that**, not the archive. Parent sampling makes a search wider; it does
nothing to make it safer, and this run shows both facts in consecutive turns.

### The two seeds that did not climb, and why they are not noise

Seeds 4 and 7 stopped at turn 2 having proposed `BATCH_SIZE = 4` twice —
`_choose_parent` drew the ROOT, the proposal was the already-rejected tree,
and `run_loop` stopped. Both sources of chance were named in the
pre-registration before the sweep:

- **the parent draw.** At turn 2 the root weighs 0.25 (score `None` → 0.5, one
  child) and the rejected stone weighs 0.6355 (score 0.5556, no children), so
  P(the sampler draws the stone) ≈ 0.72. Eight of ten is what that predicts.
- **the cohort.** From a parent at 4 a cohort member can land on 5 and tie the
  candidate, and G3 rejects a candidate that does not BEAT the p95. Estimated
  ≈ 0.16 per run. **It fired in none of the eight**, which is luck in this
  measurement's favour and is stated as such rather than left for a reader to
  notice.

So the honest reading of "8 of 10" is: the mechanism pays whenever the sampler
draws the stone, and the sampler draws the stone about seven times in ten.

## 3. A defect found by RUNNING, which had already produced a whole false arm

The first sweep of ten seeds reported `stepping_stone_keeps = 0` in **both**
arms — the same headline number as ADR 0198, from a rig built to break it.
The turn log said why, and nothing else would have:

```
G1 rejected it: build command failed (exit -1):
python -c import agents.ladder.graph as g; g.build_graph()
```

`python` was not on `PATH`. Every candidate was rejected by G1 before any
behavioural gate ran, every rejection was scored `None`, `_parent_weight`
returns 0.0 for a rejected member with no score — *"recorded, never a
parent"*, ADR 0160's rule, working exactly as designed — so the archive held
two members neither arm could ever sample from, and the sampling arm was
mechanically identical to the greedy one.

Three things worth carrying out of that:

1. **A null result from a broken harness is indistinguishable from a null
   result about the thing under test**, at the level of the headline number. It
   was distinguishable in the raw log, which is the argument for committing
   turn-level records rather than summaries.
2. **`_parent_weight`'s zero for an unscored reject is doing real work**, and
   this is the first time anything has demonstrated it on a live run rather
   than in a unit test.
3. It is now in `docs/research/j2c/README.md` as a prerequisite, because the
   next person to run this will hit it.

## 4. Should `sample_parents` be deleted? — No, and this is the run that settles it

ADR 0198 set the condition in advance:

> If a rig with both halves is built and sampling still buys nothing there,
> **that is the run that deletes it.** This one still cannot.

This is a rig with both halves. Sampling bought something: 8 keepers against
greedy's 0, every one of them a descendant of a rejection, at the rung the
probe predicted. Four measurements now:

| | rig | what sampling did |
|---|---|---|
| ADR 0121 (I6) | summary corpus | no different behaviour at all — the deterministic proposer re-emitted the identical tree |
| ADR 0160 (S4) | summary corpus | 5 distinct parents against greedy's 1; **nothing kept in either arm**, so the statistic had no power |
| ADR 0198 (N8) | `agents/demo` | built on a rejection 5 times, three generations; **0 keepers**, because the second step was on an axis the proposer cannot walk |
| **ADR 0203 (P4)** | **`agents/ladder`** | **8 keepers from a rejection in 10 seeds; greedy 0, and provably cannot** |

**`sample_parents` stays off by default** — that is unchanged, and nothing here
argues for flipping it. What has changed is the sentence beside the default. It
used to be *"a working mechanism with a measured null result, a named reason,
and a stated experiment that would overturn it."* It is now: **a mechanism
measured to pay when, and only when, the search landscape has a plateau on the
axis the proposer walks and a better position beyond it.** Turning it on is
still an owner's decision, and the thing an owner needs to know before making
it is whether their agent's landscape has that shape — which `--probe` is how
you find out, in zero calls.

## Decision

- Rubric dimension 6: **8 → 10**. The pre-registered falsification was *"a
  keeper descends from a rejected candidate"*; it does, in 8 of 10 seeds, at
  the predicted rung, against a greedy arm that structurally cannot.
- `agents/ladder/` is added; `agents/demo/` is **not modified**, so ADR 0198's
  measurement still re-derives against the fixture it was made on.
- `docs/research/j2c/corpus/` is this worker's own corpus copy. The
  repository's `corpus/` was another worker's this wave and was not touched.
- The table is registered in `docs/research/measure.py` as `j2c-staircase`
  and re-derives from the committed JSONL with **zero live calls**.

## Mutations

Against `tests/harness/test_ladder_staircase.py`, this increment's own
tripwire: perturb, RUN, restore from a sha256-verified byte backup. The
control is green before and after.

| # | mutation | result |
|---|---|---|
| M1 | move `BATCH_SIZE` below the decoys, so `proposals[0]` walks a different axis | **1 failed** — CAUGHT |
| M2 | raise the frame ceiling so rung 6 no longer collapses | **3 failed** — CAUGHT (see below) |
| M3 | shift the predicate so rung 4 is not neutral | **5 failed** — CAUGHT |
| M4 | `RuleBasedProposer.step` 0.25 → 1.0, so 4 is not what it proposes from 3 | **1 failed** — CAUGHT (see below) |
| M5 | a keeper whose parent was KEPT, counted as a stepping-stone keep | **1 failed** — CAUGHT |

5 of 5 — **on the second pass. Two escaped the first one, and both escapes
were real.**

**M4 escaped because the test pinned the proposer's step to a copy of
itself.** The first version asserted `coerce_value(batch, batch.value * 1.25)
== 4.0` with `0.25` written as a local literal and a comment saying
"RuleBasedProposer.step". Changing the shipped default to 1.0 — which would
make the proposer step from 3 to 6, straight past the stone and off the cliff,
destroying this whole rig — left the test green. A test that names a constant
in a comment and re-declares it in the body asserts nothing about the code it
names. It now reads `RuleBasedProposer().step`, and the mutation is caught.
This is exactly the shape ADR 0162 found in its own rig (the runner holding a
copy of the shipped prompt) and it recurred here in a smaller form.

**M2 escaped because of a stale `.pyc`, which is ADR 0198's defect biting a
third time.** `320 // 64` and `640 // 64` are the same number of bytes, and
CPython invalidates a `.pyc` on mtime-in-seconds plus size — so the mutation,
written and run inside one second, silently re-executed the ORIGINAL bytecode
and reported itself as uncaught. ADR 0198 hit this in its staircase probe and
fixed it there with `PYTHONDONTWRITEBYTECODE`; the probe here inherited the
fix and the mutation harness did not. **A mutation check that runs stale
bytecode reports "not caught" for a control that works and "caught" for
nothing at all — it can only ever produce false alarms, but a false alarm that
sends someone to weaken a control is not harmless.** Any harness in this repo
that rewrites a Python file and immediately imports it needs the variable;
that is now three places.

## Consequences

- Dimension 6's full-marks text — *"candidate lineage kept; parents sampled
  for diversity, not just the current best; stepping stones survive"* — now has
  a measurement in which a surviving stepping stone is the only route to the
  best position the loop found.
- The generality claim is **narrow and stated**: one fixture, one proposer,
  one corpus, a landscape built to have the shape. What is shown is that the
  mechanism *can* pay and what the landscape has to look like; what is not
  shown is that any real agent's landscape looks like that. `agents/demo`'s
  did not, and neither did the summary corpus's.
- The next honest increment for this row is not another A/B. It is `--probe`
  run against a real agent's real tunables to find out whether the shape
  occurs in the wild.

## Confidence

**High on the result.** Twenty runs, 10 seeds per arm, every one committed at
turn level; the greedy arm's zero is a proof rather than an observation
(`proposals[0]` from an unmoving kept ref is the same tree every turn); the
keeper's score and its parent's score are the probe's own numbers, so the
climb is the one the staircase predicted.

**High on the mechanism's identification**, because the failed first sweep is
the control nobody designed: with G1 rejecting every candidate before it could
be scored, the sampling arm collapsed onto the greedy arm exactly as
`_parent_weight` says it should.

**Low on generality**, deliberately and for the same reason as ADR 0198's own
closing note. A fixture built to have a staircase has one. The number that
would change this row again is how often a real agent does.
