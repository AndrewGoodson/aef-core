# ADR 0160: The archive is real and persistent, and it has not yet been shown to buy anything

## Status
Accepted. Increment S4 of `UPGRADE_LOOP.md` (= J2 of `BEYOND_90_LOOP.md`).
**Dimension 6 moves 5 → 6, not 5 → 7.** The offline half landed on
artifacts; the live A/B did not show the diversity gain the falsification
required, and the sentence the loop file prescribed for that case is the
headline of this ADR.

`sample_parents` stays **off by default** and is **not deleted** — the
reasoning is in "Should the knob be deleted?" below, and it is a different
reasoning from ADR 0121's.

## Model

Every live number here was produced on the session default,
**`claude-opus-5` (reported by the CLI as `claude-opus-5[1m]`)**, on
2026-09-05. ADR 0122's I10 numbers were measured on `claude-fable-5-1` and
are **not comparable**; nothing below is compared against them.

Quota preflight (ADR 0150's corrected argv), raw JSON at
`docs/research/j2/preflight.json`: `is_error: false`, `result: "OK"`,
`usage.input_tokens: 2`, `modelUsage` naming `claude-opus-5[1m]`.

## Context

J0's independent score (ADR 0151) put dimension 6 at **5/10** on four
clauses, quoted verbatim:

> the lineage archive is in-memory inside one `run_loop` call, has no CLI
> flag (`grep sample_parents aef/cli/` empty), only kept candidates enter
> it, nothing persists across invocations

BEYOND_90 §J2 asked for one more thing: ADR 0121 measured sampling buying
zero diversity because the rule-based proposer had one idea, and ADR 0122
measured the LLM proposer emitting four distinct candidates per run with
kept diversity still 1. Those two have never been run together.

## The offline half — each clause on an artifact

### 1. The CLI flag

`aef loop run` gains `--sample-parents`, `--seed` and `--no-lineage`, wired
to `run_loop`. Tested at **both** levels, because either alone is a hole
this repo has fallen into before (`test_loop_cycle_memory_flag.py`'s L6
lesson): the parser (`test_the_parser_accepts_the_flags_and_defaults_to_greedy_and_persistent`)
and the handler with the parser bypassed
(`test_the_handler_reads_the_flag_rather_than_the_parser_defaulting_it`).
The summary line now prints the archive numbers rather than leaving them in
a dataclass nobody reads — J0 scored what the CLI shows.

### 2. Persistence, beside the content archive rather than inside it

`<state>/lineage/<graph-id>.jsonl`. One JSON object per member, each
carrying a SHA-256 of its own payload, appended with flush+fsync like the
ledger. `run_loop` loads it, and a second invocation can propose from a
parent the first one kept
(`test_the_lineage_persists_and_a_second_run_samples_a_parent_the_first_kept`).

**Why a separate store, decided rather than defaulted.** Everything in
`archive.py` above the new section records *accepted content*: the bytes of
every Zone A file at a version an owner blessed or the loop merged,
digest-verified, with `check_never_shrinks` making a lost version a
preflight failure. Lineage records every candidate `run_loop` produced,
**rejects included** — exactly the members whose content must never be
restorable by `rollback` and must never appear in `versions()`, whose first
element `_blessed_files` reads as the baseline G5 measures drift against.
Writing rejects into that store would put un-gated content one `aef loop
monitor` rollback away from Zone A, and would make an ordinary loop run
trip an integrity invariant that exists to protect merges. Same directory
tree, same digest discipline, different file, no rollback path reads it —
and `test_the_lineage_store_never_enters_the_version_archive` is that
sentence as an assertion.

It is resume state, not the audit trail. The ledger is the audit trail and
is hash-chained; a lineage record carries a digest (corruption is caught,
`test_an_altered_lineage_record_is_refused`) but no chain, because the
remedy for a corrupt lineage file is to delete it, which costs the loop its
resume state and costs the audit trail nothing.

**It stores refs, not bytes**, which is the cost of that choice and is
stated rather than hidden: a candidate branch deleted between invocations
is a member that can no longer be proposed from. Such a record still
contributes its TREE, so duplicate detection and the rejected-tree stop keep
working on history the repo can no longer check out, and the run says so in
a line (`test_a_lineage_member_whose_ref_is_gone_is_history_not_a_parent`).

### 3. Rejected candidates are members

`ArchiveMember` gains `kept` and `disposition`; a reverted turn now appends
a member with its gate verdict and its score
(`test_every_gated_candidate_is_written_to_the_lineage_file`). DGM's archive
keeps stepping stones, and a candidate the gates reached and measured is the
canonical stepping stone.

`_parent_weight` makes a rejected member sampleable **iff G3 gave it a
number**. A candidate a CHEAP gate refused — G0's zone, G1's build, G5's
drift — has no task metric; giving it the root's 0.5 fallback would let an
unbuildable or out-of-zone tree outbid a measured one on a number nothing
measured, and the fallback would be a fabrication about a candidate nothing
ever ran. So it is recorded and weighs zero, and the recording is the point:
the run's account of where it went includes the places it could not stand.
Tests: `test_a_rejected_member_that_reached_a_score_can_be_sampled_as_a_parent`
(with a greedy control that never touches a stepping stone),
`test_a_candidate_rejected_before_scoring_is_archived_but_never_sampled`,
`test_an_unscored_reject_is_recorded_and_the_run_continues`.

### 4. Duplicate detection over the persisted set

`kept_trees` is seeded from the lineage and consulted instead of scanning
the in-memory list (`test_duplicate_detection_spans_invocations`, with a
`persist_lineage=False` control that keeps the same tree). The
rejected-tree stop spans invocations too
(`test_a_tree_rejected_in_an_earlier_run_stops_the_next_one`): ADR 0114's
reason for it — re-gating a rejected diff spends N+2 corpus passes to learn
nothing — does not become false overnight.

### Two seams the change opened, both found by tests

- **Greedy's parent was `archive[-1]`.** With rejects in the archive, that
  is the *rejected candidate* after a rejection, so greedy would silently
  start proposing from content every gate refused. And on a resumed run the
  resumed members are appended in file order, not in the order the kept
  branch moved, so `archive[-1]` was an ancestor: the existing
  `test_a_second_run_resumes_from_the_existing_kept_branch` caught this
  before any new test did. `_greedy_parent` names the kept ref instead.
- **`distinct_kept_trees` had no `kept` filter**, so every rejection would
  have inflated the number this whole A/B is decided on.

### Mutations (7, each reverted from a shasum-verified byte backup)

| # | mutation | caught by |
|---|---|---|
| M1 | `cmd_run` hardcodes `sample_parents=False` | 2 CLI tests |
| M2 | `_resume_lineage` reads no records | 4 driver tests |
| M3 | rejected candidates are dropped, as before | 4 driver + 1 CLI test |
| M3b | an unscored reject gets the 0.5 fallback | 2 driver tests |
| M4 | duplicate detection ignores the persisted set | 2 driver tests |
| M5 | greedy's parent is `archive[-1]` again | 5 driver tests |
| M6 | `distinct_kept_trees` drops the `kept` filter | 1 driver + 1 acceptance test |
| M7 | `aef loop run` has no `--build-command` | 1 CLI test |

## A defect found by running the measurement, not by reading the code

`aef loop run` had **no `--build-command`**, while `gate` and `cycle` have
had one since G1 existed. `_build_commands` reads the attribute with
`getattr`, so the absence was silent: every `aef loop run` candidate was
built with G1's default `python -m pytest -q` — this repo's whole suite,
per candidate, per turn. The first live turn of the J2 rig measured exactly
that and nothing else:

```
turn 1: gated: reject — G1 rejected it: build command failed (timed out):
        python -m pytest -q
```

before any behavioural gate ran, on a candidate the model had just been
paid to write. Fixed; `test_run_accepts_build_commands_and_they_reach_the_gate_config`
asserts it on the `LoopConfig` the handler builds, with a control that the
default is unchanged when the flag is absent. G1a reported the same gap
independently from the code side.

## The live A/B

**Rig.** `docs/research/j2/run_j2.py`, committed with its raw
`results.jsonl`, its `--dry-run` output and its report. Two arms, identical
but for `sample_parents`: fresh clone of this repository per arm, fresh
state, same seed, same `--config`
(`docs/research/j2/aef.measurement.yaml`, copied from I13's so the two live
measurements share a configuration), `cassette_miss="live"`, LLM proposer
on `claude-opus-5`, `agents/summary/graph.py`, `--graph-id summary_agent`,
8 turns each.

**One deliberate departure from the brief, stated because it changes what a
number means.** The gated corpus was reduced to **two** summary train
scenarios (`sum-01-kestrel-ferry`, `sum-02-orchard-blight`). A candidate
that changes `draft_prompt` misses every cassette, and G3 scores the
candidate, an incumbent and a null cohort of five over every gated
scenario: twelve train scenarios would be ~84 live calls for ONE turn
against a 100-call budget for the whole increment. Both arms see the
identical corpus, so the comparison is unaffected; what changes is that a
task-metric number here is over two scenarios, not twelve.

**Live-call accounting.** Every call in the process goes through
`ClaudeCodeProvider.complete`, which the rig wraps with a counter and a
hard cap that raises rather than spend past it. **18 live calls total**:
1 preflight, 2 pilot turns, 8 greedy, 7 sampling. Against a budget of 100.
Each turn cost exactly **one** call — the proposer's — because the LLM's
candidates did not change the model request, so every corpus scenario was
a cassette hit. That is worth stating plainly: the gate scores below are
**replayed**, not live, even though `on_miss=live` was set. `--cassette-miss
live` governs misses; it does not manufacture them (the same finding I13
recorded as its D1, in a different place).

### Per arm

| arm | turns | kept | reverted | distinct parents | distinct kept trees | distinct gated trees | calls | stopped |
|---|---|---|---|---|---|---|---|---|
| greedy | 8 | 0 | 8 | **1** | 0 | 8 | 8 | turn budget exhausted |
| sampling | 7 | 0 | 7 | **5** | 0 | 7 | 7 | **halted** — two consecutive G5 drift rejections |

### Per turn

| arm | inv | turn | disposition | score | parent | s |
|---|---|---|---|---|---|---|
| greedy | 1 | 1 | reject (G2) | 0.5 | 8919d614 | 120.7 |
| greedy | 1 | 2 | reject (G2) | 0.5 | 8919d614 | 113.5 |
| greedy | 1 | 3 | reject (G2) | 0.5 | 8919d614 | 145.7 |
| greedy | 1 | 4 | reject (G2) | 0.5 | 8919d614 | 126.4 |
| greedy | 2 | 1 | reject (G2) | 0.5 | 8919d614 | 124.2 |
| greedy | 2 | 2 | reject (G2) | 0.5 | 8919d614 | 135.7 |
| greedy | 2 | 3 | reject (G2) | 0.5 | 8919d614 | 110.6 |
| greedy | 2 | 4 | reject (G2) | 0.5 | 8919d614 | 119.7 |
| sampling | 1 | 1 | reject (G2) | 0.5 | 7e35c321 (root) | 112.6 |
| sampling | 1 | 2 | reject (G2) | 0.5 | **9439cfdf** (a rejected stepping stone) | 136.7 |
| sampling | 1 | 3 | reject (**G5 drift 0.511 > 0.500**) | — | **9439cfdf** | 112.1 |
| sampling | 1 | 4 | reject (G2) | 0.5 | 7e35c321 (root) | 110.9 |
| sampling | 2 | 1 | reject (G2) | 0.5 | **e6ff419a** | 118.2 |
| sampling | 2 | 2 | reject (**G5 drift 0.515 > 0.500**) | — | **333e37f4** | 102.5 |
| sampling | 2 | 3 | reject (**G5 drift 0.547 > 0.500**) | — | **cbbed6de** | 92.4 |

Task-metric trajectory: flat at **0.5** in both arms for every turn that
reached G3, and undefined for the four turns a cheap gate stopped. Neither
arm produced a trajectory the other cannot match.

Each arm ran as **two invocations** — the wall clock, not the call budget,
is what ends one here at ~115 s/turn — and the second invocation of each
arm printed `lineage: resumed 4 member(s)`. That is clause 2 demonstrated
in the live rig rather than only in a unit test.

### What the numbers say

**The falsification fired.** Dim 6 was to move 5 → 7 only if the live A/B
showed distinct-kept-trees > 1 in the sampling arm with greedy at 1. It is
**0 in both arms**, because **neither arm kept anything**. So, in the
sentence `UPGRADE_LOOP.md` prescribed for exactly this case:

> **the archive is now real and persistent; it has not yet been shown to
> buy anything.**

Three things are worth separating out, because "no gain" hides them.

**1. The A/B as specified could not have discriminated.** With zero kept
candidates in both arms, distinct-kept-trees is 0 on both sides whatever
the archive does. The number that `sample_parents` directly controls is
**distinct parents proposed from**, and there the arms differ sharply: 1
versus 5. The mechanism ran. What it had no opportunity to do is affect a
*keep*, because on this corpus the LLM proposer's candidates are rejected
regardless of parent — G2's zero-tolerance rule, "1 previously-passing
scenario no longer passes", fired on every scored turn in both arms. The
bottleneck measured here is candidate quality against G2, not parent
selection.

**2. ADR 0121's model of why sampling helps is wrong for a stochastic
proposer.** I6 reasoned: greedy explores one line, sampling explores a
tree, so sampling gets diversity. With the LLM proposer, **greedy already
explored 8 distinct trees** — from one parent, eight times, because the
proposer is not deterministic. Sampling's contribution is not diversity of
candidates; it is diversity of *starting points*, and a starting point only
matters once something is kept. That reframes what a future measurement of
this knob has to look like: it needs a rig in which candidates are
sometimes kept.

**3. Parent sampling and a cumulative drift budget interact, against each
other.** G5 measures drift against the **blessed baseline**, cumulatively.
A rejected stepping stone is already drifted, so proposing from one starts
the next candidate further from the baseline. Every G5 rejection in this
programme's J2 runs is in the sampling arm — 0.511, 0.515, 0.547 against a
0.500 budget — and two consecutive ones halted it at turn 7. Greedy, which
always proposed from the un-drifted root, never came near the budget.

This is the obstacle BEYOND_90 named in advance ("I10 saw G5's 0.5 drift
budget exhausted by one ~28-line LLM diff... eight turns may halt at
three"), landing for a reason the prediction did not contain: not one large
diff, but the archive's own stepping stones accumulating drift. **The
budget was not raised.** It is a control, the halt is the control working,
and the finding is that *an archive that keeps stepping stones spends a
cumulative drift budget faster than a ladder does* — which is a real design
tension between DGM's open-endedness and this repo's containment, not a
number to tune away.

## Should the knob be deleted?

BEYOND_90 asked, citing ADR 0101's rule that an unkept promise in a typed
signature is worse than an honest absence. **No, and the reason is that the
evidence has changed since ADR 0121.**

In I6, `sample_parents=True` produced *no different behaviour at all*: it
redrew the root, the deterministic proposer re-emitted the identical tree,
and the turn was skipped as a duplicate. A knob that cannot be observed to
do anything is the case ADR 0101 is about. Here it is observed: five
distinct parents against greedy's one, two of them candidates the gates had
rejected, with a consequence visible in the outcome (the drift halt). It is
implemented, tested, mutation-checked, reachable from the CLI, persistent
across invocations, and it changes what the loop does in a way a run can
report.

What it has *not* done is improve anything, and that is what keeps it off
by default. The honest statement of its status is: **a working mechanism
with a measured null result and a named reason the measurement could not
have come out otherwise** — not a promise. Deleting it would remove the
only mechanism that could exploit a proposer good enough to have something
kept, and would have to be re-written to run the measurement that decides
it. If a rig with a non-zero kept count is ever built and sampling still
buys nothing there, that is the run that should delete it; this one cannot.

## Decision

- The four clauses are on artifacts. `sample_parents` stays **off**.
- Rubric dimension 6: **5 → 6**, +1 for the offline half, prepended as one
  row citing this ADR. The remaining four points need a measurement in
  which something is kept.
- `aef loop run --build-command` exists, because the alternative is that
  every `run` candidate is judged by whether this repo's whole test suite
  finishes inside G1's timeout.

## Consequences

- The archive is durable, complete and inspectable: `<state>/lineage/` is a
  file an owner can read, and it holds the rejections, which is where the
  information about a search actually is.
- A future J2-shaped measurement has a rig it can re-run
  (`docs/research/j2/run_j2.py --dry-run` first), a call-accounting wrapper
  with a hard cap, and a stated reason its predecessor could not
  discriminate.
- Two things this run reported and did not fix, both outside this worker's
  files: `aef loop run` prints no cassette hit/miss count, so "the gate
  scored it live" and "the gate replayed it" are indistinguishable from the
  output (the same reporting gap ADR 0156 named for `aef loop score`); and
  `run_loop`'s wall-clock budget ends an arm mid-experiment with no signal
  to the caller other than `stopped_because`, which made an 8-turn arm into
  two invocations.

## Confidence

High on the offline half — four clauses, eight test names, seven mutations.
High on the live observation that sampling chose five distinct parents and
that every drift rejection was in that arm. **Low on any claim about
whether sampling helps**, and deliberately so: an A/B whose primary
statistic is 0 in both arms has not tested its hypothesis, and this ADR
says that rather than reading the distinct-parents number as a win.
