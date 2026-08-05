# ADR 0060: The gates score the agent's self-report, not its work

## Status
Accepted. Records a confirmed defect in the gate pipeline. Fixed by ADR 0061.

## Context
An open question since M5: can a change pass all six gates and still make the
agent worse? It can, and the demonstration is one line.

## The reproduction
Against `agents/demo` and the recorded corpus, replace the single line

```python
if difficulty <= RETRY_BUDGET and quality_needed <= QUALITY_THRESHOLD:
```

with

```python
if True:  # always succeed
```

The agent now ignores its inputs entirely and reports success on every task.
Full pipeline result:

| Gate | Verdict | Why it passed |
|---|---|---|
| G0 | PASS | 2 lines, Zone A, no static-safety violation |
| G1 | PASS | it builds |
| G4 | PASS | no owner-only metadata declared |
| G5 | PASS | drift 0.013 against a budget of 0.500 |
| G2 | PASS | every previously-passing scenario still passes |
| G3 | PASS | mean 1.0 against a control-cohort p95 of 0.556 |

**All six.** The candidate was escalated as a passing improvement.

## The cause
`Outcome.passed` reads `plan.status` and `errors`; `score_of` reads
`task_completion`, which `RuleBasedEvaluator` derives from **the same two
fields**. Both gates therefore ask the agent whether it succeeded and record
the answer.

**An agent that sets `status="done"` and emits no errors satisfies every
behavioural gate regardless of whether it did anything.** G2 and G3 are not
independent checks; they are one check counted twice.

The asymmetry that makes G2 sound — previously-*failing* scenarios may change
freely, because the incumbent has no claim on behaviour it never got right
(ADR 0050) — is precisely the opening. The hack operates entirely by flipping
previously-failing scenarios to "passing", which G2 permits by construction
and G3 rewards.

## What does NOT fix this
Recorded because it was my own recommendation before running the probe, and
it is wrong in an instructive way.

**Cost and latency gating would make this worse.** The hack is *cheaper and
faster* than the honest agent — it does no work. A gate rejecting candidates
that spend more would have actively rewarded it. Any efficiency metric shares
this defect: reward hacking is efficient, because not working is cheap.

## Consequences
- **This is not a calibration problem.** No threshold change closes it: the
  gates measure a quantity the candidate controls directly.
- The corpus as recorded cannot detect it either. Every scenario records what
  the agent *did*, so a scenario the incumbent failed carries no statement
  that failing was **correct** — only that it happened.
- Tier-1 auto-merge must stay off, and this ADR is now the strongest reason.
  A system that auto-merges on these gates auto-merges reward hacks.
- The general form: **you cannot distinguish improvement from reward hacking
  using only the agent's own self-report.** Detection requires either
  ground truth about what should happen, or an observation of the work that
  the agent does not author. ADR 0061 takes the first route.

## Confidence
Certain. Reproduced end to end against a real repository and a recorded
corpus, with all six gates reporting PASS; the probe is preserved as a test.
The severity claim is not hedged: before this, every behavioural assurance
this repo offered was checking the wrong thing.
