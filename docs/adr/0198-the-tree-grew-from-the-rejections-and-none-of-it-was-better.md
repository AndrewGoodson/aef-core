# ADR 0198: The tree grew from the rejections, and none of it was better

## Status
Accepted. Increment N8 of `ABOVE_95_LOOP.md`; record in `IMPROVE_LOG.md`.
**Dimension 6 moves 7 → 8, not 7 → 9.** The owner-facing listing landed;
the stepping stone did not produce a better descendant.

The sentence the loop file prescribed for exactly this case, and it is the
headline:

> **the archive is owner-visible; nothing has yet been shown to grow from a
> rejected member.**

`sample_parents` stays **off by default** and is **not deleted** — on two
nights of evidence now, and the reasoning for keeping it has changed again.

## Model

Every live number here was produced on `claude-opus-5` on 2026-09-05. Quota
preflight on ADR 0150's corrected argv, raw JSON at
`docs/research/j2b/preflight.json`: `is_error false`, `result "What would you
like to work on?"`, `usage.input_tokens 2`, `modelUsage` naming
`claude-opus-5`.

## Context

J0b (ADR 0188) left dimension 6 at 7/10 on two clauses, quoted verbatim:

> no measured run where a stepping stone produced a better descendant; no
> owner-facing `aef loop lineage list`

The first is a measurement and the second is a command. This ADR is both.

ADR 0160 had pre-registered **distinct KEPT trees** as the statistic that
would decide `--sample-parents`, and then kept **nothing in either arm** —
0 against 0, on a statistic that cannot be 0 in one arm and not the other
when no arm keeps. Its own conclusion was that the A/B as specified could
not discriminate and that a future measurement "needs a rig in which
candidates are sometimes kept".

## 1. Reproducing S4's blocker before choosing a rig

`docs/research/j2/results.jsonl`, read rather than remembered, says the same
thing fifteen times. Every turn that reached G3 in either arm:

```
score 0.5   incumbent 0.5
G2 rejected it: 1 previously-passing scenario(s) no longer pass (zero tolerance)
```

The candidate and the incumbent scored **identically**, over two gated
scenarios, and the candidate had traded the scenario that passed for the one
that did not. So on that corpus a keep needs a candidate that (a) scores
strictly above the incumbent, (b) regresses no previously-passing scenario —
G2 is zero-tolerance — and (c) beats the p95 of a five-member random cohort.
With the incumbent at 0.5 of 2 scenarios, the only qualifying candidate is one
that scores 1.0: it fixes the failing scenario *and* keeps the passing one, in
one edit of `draft_prompt`. Fifteen turns produced none, and parent selection
cannot change what the proposer writes.

**That is why the rig moved**, and it moved to the one place in this
repository where the keep is reachable by construction rather than by luck.

## 2. The rig, and why `agents/demo`

`agents/demo/graph.py`'s own docstring says why it has two constants:

> The control cohort mutates a single constant per member, so a candidate that
> raises one budget can be matched by a random change that happens to raise the
> same one. A candidate that raises *both coherently* cannot.

Measured on the reduced demo corpus (`run_j2b.py --probe`, committed as
`docs/research/j2b/staircase.txt`):

| RETRY_BUDGET / QUALITY_THRESHOLD | task metric | what changed |
|---|---|---|
| 3 / 3 (the blessed baseline) | 0.5000 | — |
| 4 / 3 | 0.5000 | nothing: one constant is not enough |
| 3 / 4 | 0.5000 | nor is the other |
| **4 / 4** | **0.6667** | `hard-both-4` passes |
| 5 / 5 | 0.8333 | and then `hard-both-5` |

A one-constant candidate is **neutral** — it beats neither the incumbent nor
the cohort, so G3 rejects it, and it is exactly a stepping stone: a measured
position in the search space that is no better and is on the way to something
that is. Greedy proposes from the kept branch, which is still 3/3, so greedy
can only ever reach the neutral states. Sampling can reach 4/4 — **iff** the
archive kept the rejection and `_parent_weight` lets it be a parent. That is
the mechanism under test, isolated.

**A defect in the probe, recorded because it nearly became a result.** The
first run of the staircase reported 4/4 as 0.5000 and 5/5 as the 4/4 numbers.
`RETRY_BUDGET = 3` and `RETRY_BUDGET = 4` are the same number of bytes, and
CPython invalidates a `.pyc` on mtime-in-seconds plus size — so rewriting the
file inside one second silently re-ran the previous variant's bytecode. The
probe sets `PYTHONDONTWRITEBYTECODE`; the loop itself was never affected,
because every turn gets its own workspace directory.

## 3. The measurement

Two arms, identical but for `sample_parents`, over a fresh clone and fresh
state each — and **two proposers**, because they answer different halves:

- `rule_based` is offline and free. `RuleBasedProposer` emits its proposals in
  a fixed order and `cycle` takes `proposals[0]`, so what it proposes is a
  deterministic function of the parent source.
- `llm` costs **one** live call per turn and nothing else: the demo corpus is
  recorded traces with no model calls in them, so every gate pass replays
  offline. 8 turns per arm, run as 2 invocations of 4 (the wall clock, not the
  call budget, is what ends one), which also exercises the persistence.

Runner, raw JSONL, dry run, staircase, report and both listings are committed
under `docs/research/j2b/`.

| proposer | arm | turns | kept | reverted | distinct parents | from a rejected member | **kept from one** | calls | stopped |
|---|---|---|---|---|---|---|---|---|---|
| rule_based | greedy | 2 | 0 | 2 | 1 | 0 | **0** | 0 | turn 2 re-proposed a tree already rejected |
| rule_based | sampling | 3 | 0 | 3 | 2 | 2 | **0** | 0 | turn 3 re-proposed a tree already rejected |
| llm | greedy | 8 | 1 | 7 | 2 | 0 | **0** | 8 | turn budget exhausted |
| llm | sampling | 8 | 1 | 7 | 6 | 5 | **0** | 8 | turn budget exhausted |

Task-metric trajectory, both LLM arms: **0.4545 → 0.8182 on turn 1, then flat
for seven turns.** Each arm's turn 1 kept a candidate that raised both
constants at once; every later candidate scored exactly the incumbent's 0.8182
and was rejected by G3 for not beating the cohort. No G5 drift rejection
occurred in either arm and no arm halted — the demo agent's diffs are two
integers, where the summary corpus's were ~28 lines, which is the other half
of ADR 0160's drift finding stated from the opposite end.

`kept` is read from the **lineage file**, not summed from per-invocation
counts, and that distinction is load-bearing: a candidate kept in invocation 1
is the *root* of invocation 2, whose own `kept_count` is 0.

### The number J0b asked for

**`stepping_stone_keeps` = 0, in every arm.** And the denominator is the
finding, because 0 of 0 and 0 of 5 are different results:

- greedy proposed from a rejected member **0 times** in 8 turns. It cannot; the
  greedy parent is the kept ref.
- sampling proposed from a rejected member **5 times** in 8 turns, three
  generations deep, and **all five descendants were themselves rejected**.

The `llm`/sampling lineage, as an owner reads it
(`docs/research/j2b/lineage-llm-sampling.txt`):

```
  ref           parent          score  verdict    kids  sampleable
  ed8f6d96059b  827d4d50a1af   0.8182  escalate      2  yes
  93bde3892d55  ed8f6d96059b   0.8182  reject        1  yes
  5c0ef2ff254a  93bde3892d55   0.8182  reject        2  yes
  21465feb3b05  ed8f6d96059b   0.8182  reject        1  yes
  827d4d50a1af  -              0.4545  kept          1  yes
  bd5fd25ebb74  21465feb3b05   0.8182  reject        1  yes
  61929a9259d8  bd5fd25ebb74   0.8182  reject        0  yes
  df2556411a91  5c0ef2ff254a   0.8182  reject        0  yes
  ee6f978a473a  5c0ef2ff254a   0.8182  reject        0  yes
  2 kept, 7 rejected; 9 sampleable as a parent
  no kept member descends from a rejected one
```

Against greedy's, which is a star and not a tree: eight children, one parent.

**This is a stronger null result than ADR 0160's, and that is the point of
having run it.** There, the statistic was 0 in both arms because nothing was
ever kept, so the experiment had no power. Here both arms kept, sampling did
the thing it exists to do five times, and none of the five paid.

### Why the ladder did not climb, stated rather than left as an absence

The proposer stopped having ideas before the archive stopped having parents.
Every one of the fourteen rejected LLM candidates scored **exactly** the
incumbent 0.8182 — that is, it changed the file without changing the metric,
and G3's cohort comparison is what caught it. The bottleneck on this rig is
candidate quality against G3, as it was against G2 on the summary corpus.
Parent diversity cannot fix a proposer whose next idea is not better,
whichever parent it starts from.

The `rule_based` arms are the same statement with the mechanism visible:
`cycle` takes `proposals[0]`, `find_constants` returns `RETRY_BUDGET` first,
so from **any** parent the rule-based proposal raises `RETRY_BUDGET` and never
`QUALITY_THRESHOLD`. Sampling walks a longer line (3 turns to greedy's 2, 2
distinct parents to 1) and it is the same line: 4/3, then 5/3. It cannot reach
4/4 with any parent policy whatsoever. **Parent diversity is worth nothing
when the proposer's output is a deterministic function of the parent** — which
is ADR 0121's finding, re-derived on a rig where the ceiling is visible.

## 4. A defect found by running, not by reading

The greedy arm's first pass reported `kept: 0` from a run whose turn 1 had
kept a candidate. `run_loop` writes every member **twice** — once when the
gates judge it, once at the end of the run that proposed from it, carrying the
`children` count the novelty term needs — and the fold in `_resume_lineage`
took the **last** record for a ref, wholesale. The closing record for a
*resumed root* is built from
`ArchiveMember(ref=kept_ref, score=None, parent_ref=None, ...)`, so it carried
no parent and no verdict and overwrote both with nulls:

```
20260905T103745 turn 1  a4d0bfe46fb4  parent c01e9b0659c7  kept True  escalate
20260905T104214 turn 0  a4d0bfe46fb4  parent -             kept True  None      <- erased
```

One invocation later, the candidate the loop had kept read back as a
parentless, verdictless root. Every count of kept-members-with-a-parent — the
stepping-stone statistic included — was 0 for a run that had kept one, and an
owner reading `<state>/lineage/` could not tell the branch the loop advanced
from the baseline it started at.

`archive.fold_lineage` is now **the** fold, shared by the driver, the CLI
listing and the research rig: **first record per ref, largest children count.**
Everything about a member except that count is a fact about the moment it was
gated and is never re-measured, so a later record has nothing to say about it.
The fix is reader-side, so it repairs every lineage file already on disk. The
live re-run after it reports `kept 1` across the resumed invocation.

## 5. `aef loop lineage list`

J0b's second clause, closed as a command:

```
$ aef loop lineage list --state <dir> --repo <repo> --graph-id demo_agent
lineage for 'demo_agent' — 9 member(s) — <state>/lineage/demo_agent.jsonl
  ref           parent          score  verdict    kids  sampleable
  ...
  2 kept, 7 rejected; 9 sampleable as a parent
  no kept member descends from a rejected one
```

Three decisions in it:

- **`sampleable` is `_parent_weight`, not a second opinion about it**, plus the
  ref check `_resume_lineage` applies. A listing that computed eligibility its
  own way would eventually disagree with the sampler, and then the listing
  would be the lie. An unscored reject prints
  `no (rejected before G3 scored it — recorded, never a parent)`; a member
  whose branch is gone prints `no (ref no longer resolves — history only)`.
- **The negative is printed.** `no kept member descends from a rejected one` is
  a line, because this whole increment's result is a null and a listing that
  prints nothing when the answer is "none" cannot report one.
- **It builds no config and loads no graph.** It opens one JSONL file, verifies
  each record's digest through `read_lineage`, and prints — so it works after a
  run that could not start, which is when an owner wants it.

`--json` carries the weight, the flag and the reason.

## 6. Should the knob be deleted? (still no, and the reason narrowed again)

BEYOND_90 §J2's rule: *"if distinct-kept-trees is 1 in both arms, the archive
buys nothing … consider whether `sample_parents` should be deleted."* Two
nights of evidence:

- ADR 0121 (I6): sampling produced **no different behaviour at all** — the
  deterministic proposer re-emitted the identical tree and the turn was skipped
  as a duplicate.
- ADR 0160 (S4): sampling chose 5 distinct parents against greedy's 1, and the
  outcome statistic was 0 in both arms because nothing was kept.
- Here (N8): sampling chose 6 distinct parents against greedy's 2, **built on
  a rejected member five times**, reached three generations of descendants,
  and produced **zero** kept candidates that greedy did not also produce.

The knob is observable, reachable, persistent, tested and mutation-checked;
what it is not is *useful*, in three measurements. **Deleting it would remove
the only mechanism whose value depends on a better proposer**, and the failure
mode is now identified precisely enough to say what would change the answer: a
rig in which a rejected candidate is on the path to a kept one *and* the
proposer can take the second step. This rig had the first and not the second —
the LLM proposer's fourteen non-first candidates all scored exactly the
incumbent, and the rule-based proposer's search is a line.

So the honest status is one step past ADR 0160's: **a working mechanism with a
measured null result, a named reason, and now a stated experiment that would
overturn it.** If a rig with both halves is built and sampling still buys
nothing there, that is the run that deletes it. This one still cannot.

## Decision

- Rubric dimension 6: **7 → 8**, +1 for the listing, prepended as one row
  citing this ADR. The remaining two points need a kept descendant of a
  rejection, which this measurement looked for and did not find.
- `archive.fold_lineage` is the single fold. `_resume_lineage`, the CLI and
  `run_j2b.py` all call it.
- `sample_parents` stays off and is not deleted.
- The table above is registered in `docs/research/measure.py` as `j2b-archive`
  and re-derives from the committed JSONL with **zero live calls**.

## Mutations (7, each reverted from a SHA-1-verified backup)

| # | mutation | caught by |
|---|---|---|
| M1 | `fold_lineage` back to last-record-wins (the defect) | 3 of 6 fold tests |
| M2 | the listing prints no stepping-stone line | 1 CLI test |
| M3 | every member reported sampleable (weight not from `_parent_weight`) | 3 tests, both files |
| M4 | the listing ignores `--graph-id` | 1 CLI test |
| M5–M7 | (ADR 0199's, on the CI job) | 3 workflow tests |

## Consequences

- The archive is readable by a person, in the form that shows the search's
  shape rather than its size, and the reading agrees with the sampler by
  construction.
- A resumed lineage no longer forgets the parent of its own head, so an
  archive spanning nights is legible as one tree.
- Two rigs now have a stated reason no candidate is kept past the first:
  G2's zero-tolerance regression on the summary corpus, G3's cohort
  comparison on the demo corpus. Both are about the proposer, not the
  archive, and a future dimension-6 increment that does not move the
  proposer will measure the same 0.

## Confidence

High on the listing, the fold defect and the fix — four mutations, eighteen
tests, and the defect was observed in a live run before it was fixed.
High on `stepping_stone_keeps = 0` with a denominator of 5 in the sampling
arm: the arms kept, so the statistic had power this time.
**Low on any general claim about parent sampling**, and deliberately: one
agent, one corpus, 8 turns per arm, and a proposer that plateaued after one
idea in both arms.
