# ADR 0165: The scheduled loop that ran every night and did nothing

## Status

Accepted. Worker J0F of the upgrade loop, closing the first of J0's seven
independent deductions (ADR 0151) at the place it lives rather than at the
place it was scored. **No rubric dimension moves** — dimension 1 is J0's to
re-earn, and the last section says what would earn it.

## Context

J0 — an agent blind to this repo's own history — read
`.github/workflows/loop-monitor.yml` and found this, on `cron: "0 3 * * *"`:

```yaml
aef loop cycle --repo . --state ~/.aef-loop-state \
  --workdir "$RUNNER_TEMP/cycle" --module agents.demo.graph \
  --runs ~/.aef-loop-state/runs --corpus corpus
```

No `--memory`. `cmd_cycle` passed `memory=None`, `aef/harness/loop.py`'s
`cycle()` took its explicit refusal branch, and the command **exited 0**.

That is ADR 0139's failure shape — *exit 0 having done nothing* — put on a
timer and left there. It is worse than the shape ADR 0139 names, for one
reason: 0139's cases are things an adopter runs by hand and reads the output
of. This one ran unattended, at 03:00, and reported success. Every morning
since the workflow was written the repo's own self-rewiring loop had a green
tick against a night in which nothing happened, and no surface anywhere said
otherwise.

## Reproduced first — the command, its output, its exit code

`PYTHONPATH` and the venv elided; paths shortened. Run against this repo, on
`main`'s code, with the workflow's own flags.

### Before — the workflow's invocation, verbatim in shape

```
$ aef loop cycle --repo . --state <scratch>/state --workdir <scratch>/work \
      --module agents.demo.graph --runs <scratch>/state/runs --corpus <scratch>/corpus
  preflight: 5 of 6 obligation(s) unmet (reflect node routed to, observations, halt
    channel, blessed baseline, model calls visible). ADVISORY — this command does not
    refuse on them; run `aef loop doctor` for each fix.
  ledger verified: 0 entr(ies)
  promoted 0 run(s) to the train split
  no memory store configured: nothing to learn from, no candidate
EXIT=0
```

The last line is the whole defect. It is accurate, it is four lines deep in a
CI log nobody opens on a green run, and it is followed by exit 0.

### Before — the same invocation, plus one admissible failure record

One `MemoryRecord(kind="failure")` with `verbal_feedback`, a `run_id` in no
corpus split, written to a JSONL file:

```
$ aef loop cycle ... --memory <scratch>/memory.jsonl --agent-path agents/demo/graph.py
  preflight: 4 of 6 obligation(s) unmet (...)
  ledger verified: 0 entr(ies)
  promoted 0 run(s) to the train split
  proposed cycle-20260905T020022-0 on local branch loop/cycle-20260905T020022-0
    (never pushed; proposer=rule_based)
  gated: reject — G1 rejected it: build command failed (exit 1): python -m pytest -q
EXIT=1
```

Nothing was broken. One flag was missing, and its absence was silent.

### After

```
$ aef loop cycle --repo . --state ... --workdir ... --module agents.demo.graph \
      --runs ... --corpus ...
error: a cycle without memory cannot propose — with no recorded failures the proposer
has nothing to ground in, so the cycle prints 'no memory store configured: nothing to
learn from, no candidate' and exits 0, which reads as success (ADR 0139). Pass --memory
<file> — the SAME file `aef loop bootstrap --memory` and the reflect node write — or
pass --no-memory to say you mean that. Neither was given, and silence used to mean
--no-memory: this repo's own scheduled cycle was a no-op every night (ADR 0165).
EXIT=2
```

```
$ aef loop cycle ... --no-memory
  preflight: 5 of 6 obligation(s) unmet (...)
  ledger verified: 3 entr(ies)
  promoted 0 run(s) to the train split
  no memory store configured: nothing to learn from, no candidate
cycle verdict: no memory store configured: nothing to learn from, no candidate
  (--no-memory was passed: this cycle could not propose)
EXIT=0
```

```
$ aef loop monitor --repo . --state ...          # after three such cycles
checked 0 merged change(s)
  cycles run: 3 (last 0.0 day(s) ago)
  last PROPOSED: 0.0 day(s) ago
  last KEPT/MERGED: never
  WARNING: SCHEDULED CYCLE PRODUCING NOTHING — 3 consecutive cycle(s) have run and
  proposed nothing. Last verdict: 'no memory store configured: nothing to learn from,
  no candidate (--no-memory was passed: this cycle could not propose)'. A cycle that
  runs every night and never proposes is exit 0 having done nothing (ADR 0139); check
  that --memory names a file something actually writes.
```

## Decision

### 1. One of `--memory` / `--no-memory` is required on `aef loop cycle`

Exactly ADR 0141's `--state` / `--no-loop-state` shape, applied to the flag
whose absence made the loop a no-op. The reasoning transfers without change:
**a control whose enforcement the caller opts into by staying silent is not a
control**, and "do nothing" must be something the owner *says*.

`--no-memory` keeps today's behaviour precisely — the cycle still preflights,
still verifies the ledger, still harvests, and still prints the no-candidate
line — and adds one summary line saying the silence was chosen.

**Enforced in the handler, not only in the parser.** L6's finding was a
parser-level test blind to a handler-level refusal; the inverse hazard is the
same one, since `cmd_cycle` is importable and any caller can build its own
`Namespace`. `tests/cli/test_loop_cycle_memory_flag.py` asserts the refusal
with the parser bypassed entirely, and separately pins that the parser still
accepts the bare form — so the two levels stay honest about which is
load-bearing.

**Exit 2, not 1.** `cmd_cycle`'s own comment already says why: a missing flag
is a configuration error, and reporting it as a verdict on a candidate makes
CI retry it forever (ADR 0075). It shares the number with `EXIT_HALTED`, which
was checked rather than assumed: everything that reads exit 2 from this CLI is
told *stop, do not retry, a human must look*, which is the correct instruction
for an invocation that cannot work. The two are distinguishable in the output
— a halt prints `HALTED:` on stdout, this prints `error:` on stderr, as
argparse's own usage errors do.

### 2. `aef loop monitor` reports whether the loop is producing anything

`days since last PROPOSED`, `days since last KEPT/MERGED`, and a named warning
— `SCHEDULED CYCLE PRODUCING NOTHING` — when cycles have been running and
proposing nothing. This is the metric that would have caught the defect on
night three instead of never.

**It cannot be built from the ledger alone, and that is the interesting
part.** `cycle` writes a ledger entry when it *proposes*. A cycle that
proposes nothing writes nothing at all, so the ledger of a loop that has run
180 nights and produced nothing is byte-for-byte the ledger of a loop nobody
has ever started. The failure's signature is silence, and a missing signal
cannot be the alarm for itself. So `cmd_cycle` journals every attempt —
timestamp, whether it proposed, and the verdict in the cycle's own words — to
`<state>/cycles.jsonl`, and the alarm is `attempts exist AND none of the last
N proposed`. `tests/harness/test_monitoring_cycle_staleness.py::test_the_ledger_alone_cannot_tell_the_two_cases_apart`
is that argument as an assertion.

The journal is deliberately **not** the ledger. The ledger is a tamper-evident
hash chain of decisions about candidates; "a cycle ran and decided nothing" is
not a decision about a candidate, and putting non-decisions in it would make
the cycle mutate the audit trail on every no-op night.

Threshold: three consecutive quiet cycles. Not tuned — "long enough that one
quiet night is not an alarm, short enough that a broken invocation is caught
inside a week" — and it is a parameter, not a constant.

A loop nobody has run gets **no** warning. An unstarted loop is not stale, it
is unstarted, and a warning that fires on the ordinary case trains the reader
to skip the line.

### 3. This repo's workflow

`--memory ~/.aef-loop-state/memory.jsonl`, inside the already-cached
`~/.aef-loop-state`. `--state` is unchanged. The cycle's output, including the
new `cycle verdict:` line, is teed into `$GITHUB_STEP_SUMMARY`, and so is the
monitor's — so "no candidate", and the reason for it, appear in words on the
run page rather than four lines into a collapsed log.

One thing the old step got wrong that the fix would have made worse: with
`--memory` present the cycle can now reach exit 1, which is an ordinary
rejection, and GitHub's default `-e` shell would have failed the job and
routed every normal rejection into `Surface a halt`. The step now fails only
on exit ≥ 2. An alarm that fires on the normal outcome is an alarm nobody
reads.

## What this does NOT fix, stated plainly

**The memory file in CI will be empty.** Nothing in
`.github/workflows/loop-monitor.yml` records runs, and `~/.aef-loop-state/runs`
is populated by no step. So from tonight the nightly cycle will say

> no admissible failure memory: no candidate this cycle

instead of

> no memory store configured: nothing to learn from, no candidate

That is a strictly better sentence — it is the truth, it distinguishes "the
operator forgot" from "the agent has learned nothing yet", and it is now on
the run summary page in words with a staleness warning behind it. **It is not
yet a loop that learns from CI.** The scheduled cycle remains a no-op; the
difference is that it is a *visible, named, chosen* no-op instead of a silent
one, and that after three nights the monitor says so.

Turning it into a loop that learns needs something in CI to execute the demo
graph against real inputs, write reflections into that same file, and record
runs into `~/.aef-loop-state/runs` — a `aef loop bootstrap --memory` step, or
a recorded-runs step ahead of the cycle. That is a separate change with its
own measurement (does the proposer produce anything from what CI can
generate?), and claiming it here without running it would be the exact habit
ADR 0151 charged eighteen points for.

## What would re-earn rubric dimension 1

Not this ADR. Dimension 1 is "closed measurement loop", and J0's deduction was
"**nothing runs it unattended**" — three findings, of which this fixes one and
a half:

1. *The scheduled cycle is a no-op.* Now refused, journalled, summarised and
   alarmed on — but, per the section above, still a no-op until CI writes
   memory. **Half.**
2. *One candidate per turn, nothing near autoresearch's ~100 runs/night.*
   Untouched.
3. *The 2-scenario holdout is read by no automated comparison.* Untouched.

The row moves when a scheduled run has *proposed* a candidate and the ledger
shows it, which is a thing to demonstrate from a CI log, not to argue for.

## Mutations

Five planted, five caught, every restore verified byte-identical by SHA-256.

| # | Mutation | Caught by |
|---|---|---|
| M1 | `_require_memory_flag` returns `None` unconditionally | `test_neither_flag_is_refused_and_does_not_exit_zero`, `test_the_refusal_is_in_the_handler_not_only_the_parser` |
| M2 | the staleness warning never fires (`if False:`) | 4 staleness tests + `test_the_monitor_names_the_loop_that_has_been_producing_nothing` |
| M3 | `--memory` deleted from `loop-monitor.yml` — i.e. the original defect, restored | `test_this_repos_own_nightly_cycle_passes_a_memory_flag` |
| M4 | `cmd_cycle` journals nothing | `test_every_cycle_is_journalled_even_when_it_produced_nothing`, `test_the_monitor_names_...` |
| M5 | a proposal no longer resets the run of quiet cycles (`break` → `continue`) | `test_a_proposal_resets_the_run_of_quiet_cycles`, `test_only_the_trailing_run_of_quiet_cycles_counts` |

M3 is the one worth naming: the finding was in a YAML file, so an assertion
that only covered the CLI would have left the workflow free to keep doing what
it was doing. A test that reads the workflow is how a defect in a file CI never
tests gets pinned.

## Consequences

- Every generated `aef loop cycle` command line in `aef/cli/adopt_loop.py`
  (five of them) already passes `--memory`, and both `aef loop cycle`
  invocations in `tests/cli/test_adoption_sequence.py` already pass it. **No
  emitted document or test needed a flag added.** The two parser-only call
  sites — `tests/harness/test_llm_proposer.py:505` and
  `tests/harness/test_policy_config_path.py:225` — are unaffected because the
  refusal is in the handler, which is one of the reasons it is there.
- `render_loop_monitor_workflow` — the workflow `aef adopt` writes for an
  adopting repo — emits **no cycle step at all**, so adopters inherit neither
  the defect nor this fix. That is M2's increment, reported rather than
  reached from here.
- +24 tests, 2002 → 2026.

## Confidence

High on the reproduction and on the refusal: both were run, before and after,
and the exit codes are pasted above. High that the staleness warning fires on
the shape it is meant to fire on — it was driven end to end through the CLI,
not asserted on a constructed dataclass.

Medium on the workflow change, and honestly so: **the workflow itself was not
executed.** It is YAML for a scheduler this branch cannot run, so what is
proved is that the file contains the flag, that the flag is the one the CLI
accepts, and that the exit-code guard is present — not that tonight's run
behaves as described. The first real scheduled run is the evidence, and it
will be evidence of an honest no-op.

Nothing is claimed here about whether the nightly cycle will ever propose
anything, because nothing in this change makes it more likely to.
