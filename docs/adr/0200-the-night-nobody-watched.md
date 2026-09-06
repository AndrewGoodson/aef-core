# ADR 0200: The night nobody watched, several candidates a turn, and the set the loop may not choose

## Status

Accepted. Worker **P1** of `TO_95_LOOP.md`, against ADR 0188's dimension 1
(13/20) and its three clauses, quoted verbatim:

> "it has never closed unattended" · "one candidate per turn (nothing near
> ~100 runs/night)" · "the 2-scenario holdout is read by no automated
> comparison — only by `--i-am-spending-the-holdout` by hand"

Model: `claude-opus-5[1m]` (session default). **54 live model calls** of a
≤120 budget: 1 quota preflight, 5 forcing cassette misses to price a turn, 48
inside the gates' worker on the night itself. Every reproduction in this ADR
cost nothing.

The night ran on a **copy** of the peptide pilot in scratch.
`/Users/raptor/peptideindex` was not touched, read or written.

Every artefact is in `docs/research/night-1/`, including
`MORNING-REPORT.md` — the deliverable — and the two failed attempts to start
the night.

---

## 1. Reproduced first, both clauses

**One candidate per turn** (`01-repro-a.txt`, RUN). A three-constant fixture,
two failure records, the default `rule_based` proposer:

```
the proposer OFFERS 3 candidate(s) this turn:
  - repro-0 …  - repro-1 …  - repro-2 …

the turn GATED 1 candidate(s): ['loop/cycle-20260301T120000-0']
discarded without ever being measured: 2
candidate branches created: ['loop/cycle-20260301T120000-0']
```

The line was `proposal = proposals[0]  # at most one candidate per cycle,
deliberately`, and the docstring above it argued the case: "a loop that can
emit many per cycle can exhaust the rate budget in a single run". That
argument is about COST, and the answer to a cost argument is a number and a
knob, not a hard-coded 1.

Note what the reproduction also shows: the LLM proposer is *not* where the
several candidates were being lost. `LLMProposer.propose_from_memory` asks the
model **once** and returns a one-tuple; ADR 0122's "four distinct candidates
per run" was four TURNS, one candidate each. The proposer that offers several
is the rule-based one, and `RuleBasedPromptProposer` offers one by
construction (`fresh[0]`). That matters for what the night could demonstrate
— §5.

**Nothing automated reads the holdout** (`02-repro-b.txt`, RUN). The whole
population of readers:

```
aef/cli/loop.py:850   allow_holdout=args.i_am_spending_the_holdout,
aef/cli/loop.py:1065  if Split.HOLDOUT in splits and not args.i_am_spending_the_holdout:
…
.github/workflows/ci.yml:           holdout mentioned 0 time(s)
.github/workflows/loop-gate.yml:    holdout mentioned 0 time(s)
.github/workflows/loop-monitor.yml: holdout mentioned 0 time(s)

$ aef loop score agents.demo.graph --corpus corpus --splits holdout
refusing to score the holdout split without --i-am-spending-the-holdout
exit=1

corpus/holdout: sum-19-tram-depot.json  sum-20-seed-bank.json
```

The refusal works. There is no automated reader, and there are two scenarios
in it.

---

## 2. Decision A — a turn may try N candidates, and N is a price

`LoopConfig.candidates_per_turn: int = 1`, `--candidates N` on `aef loop
run|cycle`. Above 1, `cycle`:

1. takes the first N **distinct** proposals (distinct by proposed content — two
   proposals producing one tree cost two gate passes to reach one verdict);
2. materialises each on **its own branch** and gates it in **its own workdir**
   — the second is not cosmetic, it is ADR 0122's defect one level down: G1
   materialises into `workdir/workspace` and `trust._prepare_empty_destination`
   refuses a non-empty one, so a shared workdir rejects candidate 2 with a
   `TrustBoundaryError` before any behavioural gate runs;
3. gates each on an **independent pass**, and keeps the best of those that
   **passed**;
4. records the roster — every candidate, its disposition, its score, whether
   it passed — as a `CANDIDATES` ledger entry, alongside the `PROPOSED` /
   `GATED` / `REJECTED` entries each candidate already earns on its own.

**The gates' verdict logic is untouched and never sees a set.** N candidates
is N gate passes; there is no aggregate anywhere. The score only ORDERS
candidates the gates have already passed — `test_a_higher_scoring_candidate_
that_failed_is_not_kept` pins that a 0.99 the gates rejected loses to a 0.6
they accepted.

`run_loop` learns the losers' trees: a turn that gated three diffs and kept one
has REJECTED two, and without recording them the next turn can spend
cohort+2 corpus passes re-gating a diff this run already refused.

**The default is 1 and every existing measurement stands.** At N=1 the workdir
is the same workdir, no roster entry is written, and `_best_attempt` returns
the first attempt — which is exactly `proposals[0]`.

### What N costs per turn, measured

The unit is a corpus pass, and the count is `cohort_size + 2` per candidate —
1 candidate + 1 incumbent + 5 random controls. On the pilot, from the night's
own ledger:

```
evidence: 7 corpus pass(es) (28 scenario execution(s)): 1 candidate +
          1 incumbent + 5 random control(s)
```

and the night's own clock: **131 s and 24 live model calls per turn**, for 4
gated scenarios. So:

| N | corpus passes | scenario executions | live calls | wall clock |
|---|---|---|---|---|
| 1 | 7 | 28 | 24 | 131 s |
| 2 | 14 | 56 | 48 | ~262 s |
| 3 | 21 | 84 | 72 | ~393 s |

Linear, with no shared work between candidates and no way to share any: the
control cohort is generated *from the file the candidate changed*, so two
candidates that touch the same file still need two cohorts, because the null
hypothesis is about each candidate's own change. **That linearity is the whole
argument for the default staying 1**: on this pilot, N=3 is a twenty-minute
turn and 72 calls against the owner's quota.

The live-call figure is a floor and says so: it counts cassette misses, and
the incumbent arm hits the cassette whenever its Zone A tree is byte-identical
to the recording — which it was, all night.

---

## 3. Decision B — the holdout stays the owner's; a rotated slice of train does the automated read

**Both sides, since the brief asks for the argument I rejected.**

### (a) A nightly may spend the holdout on a cadence

*For.* It is the only genuinely independent set in the repository. It is
already refused by name, so a flag on a cron line is a visible, reviewable act
in git. A cadence — only after a candidate is kept, at most once per N nights
— bounds the spend, and the ledger would record every one, so "how much of the
holdout has been spent" becomes a number rather than a memory.

*Against, and this is why I rejected it.* Three reasons, in increasing order
of force:

1. **n = 2.** `corpus/holdout` holds two scenarios. A candidate-versus-
   incumbent comparison over two scenarios is not a comparison; it is two coin
   flips reported to four decimal places. The pilot's holdout holds **zero**
   — harvest promotes to train only, so an adopting repo's holdout is empty
   until the owner builds one by hand. An automated reader that fires on a
   two-element set here and an empty set there is a mechanism whose output
   nobody should act on.
2. **The cadence is conditioned on the loop's own behaviour.** "Only when a
   candidate has been kept" makes WHEN the holdout is read a function of what
   the loop did. That is not the same as choosing which scenarios are in it,
   and it is not nothing either: it correlates the read with the loop's own
   successes, which is the direction that flatters it.
3. **It converts the holdout into a second validation split, slowly, with
   nobody deciding to.** Each read informs an owner, who changes something,
   which the next read scores. That is what a validation split IS. The
   holdout's value is entirely in being read rarely, by a person, with the
   spend deliberate — `recorder.py` calls it "the owner's only independent
   read" and `proposer.py` says citing it "destroys" that. A schedule is the
   opposite of deliberate.

### (b) A rotated slice of the train split — **taken**

`audit_slice(corpus, *, at, size)`: sort the TRAIN split's scenario ids, take
`size` of them starting at `(date.toordinal() * size) % len(pool)`, wrapping.
Capped at half the train split, because a held-out set that empties the gated
set disables the gates rather than testing them.

The rule that had to survive either decision is one sentence — **the loop may
never choose which scenarios are in the set that judges it** — and the way it
is kept is the ABSENCE of arguments:

```python
def test_the_slice_is_a_function_of_the_corpus_and_the_date_and_nothing_else():
    assert set(inspect.signature(audit_slice).parameters) == {"corpus", "at", "size"}
```

No score, no ledger, no memory, no proposal, no candidate. Mutation M6 adds a
`score` parameter and the test fails.

The slice is held back from **both** places it would leak:

- **the gates** — subtracted in `_gates_with_evidence` before
  `_scenarios_for_graph`, so G2/G3 never score it. A scenario the candidate is
  gated on is a scenario the loop is selected on, and a set the loop is
  selected on is not held out;
- **the proposer's evidence** — the slice's scenarios are relabelled
  `validation` in a derived corpus, which routes them through the refusal
  `MemoryEvidence` already applies to validation and holdout records. One
  mechanism, not a second copy of it.

Then, after the gates and only if a candidate **passed**, the winner and the
incumbent are scored on the slice — two corpus passes, no control cohort,
because this is not a second G3. G3 asks "did a reasoned change beat random
changes on the set it was gated on"; this asks the one question that set
cannot answer.

**The read is advisory. It changes no disposition, and its ledger entry says
`advisory: true`.** That is the same argument as (a3), one level down: the
moment this gates, the loop is being selected against it, and it stops being
held out. What it is for is the blind spot — a candidate every gate passed
that regresses on scenarios nothing in the turn was allowed to see is exactly
the signal `05-approval-policy.md` §7 exists to surface.

### What (b) does not give you, stated

`harvest` promotes production runs into the train split, so **over many nights
the loop grows the pool this draws from.** It cannot grow tonight's pool — the
corpus read is the one loaded before the turn's harvest — and it cannot choose
which members of the pool are drawn on any night. That is a narrower guarantee
than the owner's holdout gives, and it is exactly why the holdout stays the
owner's rather than being replaced by this.

And there is a cost the night's own arithmetic makes concrete. Tonight's
rotation drew `013c9044…`, a scenario whose memory record is a *success*. On
2026-09-09 the same function draws `ddfe4cc1…`, which is one of the two runs
the lesson recurs across — so that night the lesson drops to one occurrence,
falls below the recurrence threshold, and the turn proposes nothing.
**Holding evidence back sometimes removes the evidence.** Computed, not
supposed: `docs/research/night-1/` records the four-day draw. It is the price
of the guarantee and it is why the slice rotates rather than being fixed.

**Wired where it matters.** This repo's `loop-monitor.yml` nightly passes
`--candidates 2 --audit-slice 1`, the rendered adopter nightly passes
`--audit-slice 1`, and a test asserts that **no** workflow in this repository
names the holdout flag.

---

## 4. The night

Full report: `docs/research/night-1/MORNING-REPORT.md`. In one paragraph: it
was scheduled, it fired, it ran 2 of 3 turns in 262 s, proposed one candidate
per turn grounded in two harvested production runs, was rejected both times by
G2, stopped on its own repeated-tree rule, kept nothing, moved neither `master`
nor `loop/kept`, spent 48 live calls, and left a ledger, a lineage listing, a
journal, a digest and a status a person read cold the next morning. The halt
channel did not fire, correctly, and `digest` confirmed a channel was there to
fire.

Three things came out of it that a hand-run could not produce.

**F-P1-1 (HIGH, fixed here). `aef loop run` could not propose on any adopting
repo.** `cmd_cycle` has called `resolve_graph_id_from_corpus` since ADR 0176;
**`cmd_run` never called it**. So the multi-turn driver — the one a night uses
— kept the archive-key default `"default"` as its evidence id, `MemoryEvidence`
dropped every record belonging to a `price-freshness-reviewer` scenario, and
the run printed

```
turn 1: 2 memory record(s) excluded as belonging to a graph other than 'default'
turn 1: no admissible failure memory … no candidate this cycle
stopped: turn 1 produced no candidate
```

**and exited 0.** Reproduced side by side at zero live cost on one repo, one
corpus and one memory file (`24-run-vs-cycle.txt`): identical flags, `cycle`
proposes, `run` does not. This is ADR 0165's shape for the third time — a pair
of commands, one fixed, the other left, the difference invisible because the
broken one exits 0 — and it survived two waves of fixes aimed at its twin.
Fixed, with a regression test and a pin that both turn-running commands settle
the question the same way; `GraphIdError` from `run` is now `EXIT_ERROR`.

**F-P1-2 (MEDIUM, reported, not fixed — it is not this worker's file).**
`aef loop doctor` and `aef loop digest` disagree about the same repository:
digest says `Halt channel configured: yes — /bin/sh (4 argument(s))`, doctor
says `none — a halt would tell nobody` and offers `set AEF_HALT_WEBHOOK`, the
environment variable ADR 0195 replaced. `doctor` takes no `--config`, so it
cannot read `halt_channel:` even in principle. The surface an owner is told to
run for the fix is the one giving the wrong answer.

**F-P1-3 (the measurement, not a defect). One day of calendar drift flipped a
byte-identical candidate from G2-pass to G2-fail.** ADR 0192's hand-run on
2026-09-05 recorded `G2 pass … every previously-passing one still passes`;
tonight, on the same four-line diff, `G2 fail — 4 previously-passing
scenario(s) no longer pass`. The mechanism is in the probes: the incumbent's
persona is byte-identical to the recording so its scenarios are **cassette
hits** (0 misses, 0.15 s, mean 0.8000), while the candidate's are **live**
(5 misses, mean 0.7333) — and the pilot's owner checks pin absolute day counts
(`^VERDICT: .*, 2\ days\ old$`) that the model computes from *its own* notion
of today. `fixed_clock` pins `Context.now` for the graph; it does not reach the
model's system date. So G2 compares a live candidate against a replayed
incumbent on a corpus whose checks decay one day per day.

That is a decision for an owner and the morning report lists the three options
with what each costs. Nothing here chose one.

---

## 5. What this does NOT establish

- **`--candidates 2` never had a second candidate to try.** It was configured
  on the night and the prompt proposer offers one by construction. The
  mechanism is measured on a fixture and pinned by the ledger roster in the
  tests; the night says only that it costs nothing when the proposer has one
  idea. The next increment is a prompt proposer that returns its top *k* fresh
  lessons rather than its top one.
- **The audit slice was held back and never read**, because nothing passed the
  gates. The comparison exists, is tested, and has not yet had an occasion on
  live evidence.
- **Two turns in four minutes is not ~100 runs a night**, and the gap is the
  proposer's repertoire rather than the driver.
- **`--budget-minutes` bounds when a turn may START, not how long a run
  lasts.** `run_loop` checks the clock between turns only. Worth saying; not
  fixed here.

---

## 6. Mutations

`docs/research/night-1/mutations.py`, each applied with an anchor assertion
that fails loudly rather than silently missing, tests run, file restored from
a **shasum-verified** backup with the digest re-checked:

| | | |
|---|---|---|
| M1 | `candidates_per_turn` ignored — the turn takes one | detected |
| M2 | the turn keeps the FIRST candidate, not the best that passed | detected |
| M3 | a candidate the gates REJECTED can be kept if it scored well | detected |
| M4 | the ledger roster dropped — only the winner recorded | detected |
| M5 | every candidate shares one workdir (ADR 0122's defect) | detected |
| M6 | `audit_slice` gains an input the loop controls | detected |
| M7 | the held-back scenarios are gated after all | detected |
| M8 | the held-back records stay admissible evidence | detected |
| M9 | the audit is read even when nothing passed | detected |
| M10 | a losing candidate's rejected tree is forgotten | detected |
| M11 | `loop run` stops deriving the evidence id (the night's defect) | detected |
| M12 | the nightly stops holding anything back | detected |

**12/12 detected** (`30-mutations.txt`).

---

## 7. Consequences

Rubric dimension 1: **13 → 18**, and the pre-registered falsification is met
in full — a turn can try several candidates and the ledger shows it; a
held-out set the loop cannot choose is read by an automated comparison, wired
into two scheduled surfaces; and a run nobody watched produced a morning
report. Not 20, and the two missing points are named above: no night has yet
kept anything, so the audit has never fired on a passing candidate, and
"several candidates" is a driver that can and a proposer that will not.

`test_the_cycle_proposes_at_most_one_candidate` was a source-text pin —
`assert "proposals[0]" in inspect.getsource(cycle)` — and it is replaced by a
behavioural one. The pin would have passed unchanged after this ADR, because
the literal still appears in a comment about the day it was true. A
source-text assertion cannot tell a mechanism from a memory of it.
