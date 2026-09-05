# ADR 0164: Real signal, bounded — and the falsification that fired

## Status

Accepted. Worker **S7** of `UPGRADE_LOOP.md` (BEYOND_90's **J1**). Model:
`claude-opus-5[1m]`. **No live calls of its own** — its evidence is M6 (ADR
0163), whose calls are counted there.

**Claim made in advance: dimension 7, 4 → 6 (+2), and no more.**
**Claim after the evidence: +0. Dimension 7 stays at 4/10 and the rubric is
not edited.**

This ADR exists to record a falsification firing, which is the only reason to
write down a falsification before running anything.

---

## What was pre-registered, verbatim

Dimension 7 moves 4 → 6 (+2) **only if**

- **(a)** real runs — objectives from the repo's own purpose, answered by the
  real harness — entered the corpus **through `harvest`**, with redaction on and
  the scan's counts quoted; **and**
- **(b)** the loop proposed a candidate **from that evidence**, not from
  bootstrap-synthesised inputs; **and**
- **(c)** the gates reached a verdict on it live.

With the branches written down beside it:

- if (a) holds and the cycle proposes nothing, claim **+1** with the sentence
  *"real signal entered; nothing was learned from it yet"*;
- **if `harvest` refuses every run, claim +0 and quote why**;
- the last +3 stays unclaimed either way, because marlin is the owner's own
  repository and not a third party.

## What happened

| clause | result |
|---|---|
| (a) real runs entered the corpus **through harvest** | **NO.** Five real runs recorded; `harvest` promoted 0 and rejected 5 |
| (b) a candidate proposed from that evidence | **Yes, but from `bootstrap`'s evidence**, which (b) excludes by name |
| (c) the gates reached a verdict live | **Yes** — `live_model_calls: true`, 35 executions, 30 live misses inside the worker, G0/G1/G2/G4/G5 pass and **G3 fail: 1 previously-passing scenario now scores below 0.5**; REJECT, drift 0.007/0.500 |

The third branch fired. **+0.**

## Why harvest refused, quoted

```
$ aef loop harvest agents.migrated.marlin_accela.graph --runs <runs> --corpus corpus …
promoted 0 run(s) to the train split
  5 passed, not promoted: 22a5f0ec…, 491c4102…, 7d10629e…, 999d7f25…, 9c48f5c9…

$ … --include-successes
promoted 0 run(s) to the train split
  5 REJECTED, did not re-execute deterministically: 22a5f0ec…, 491c4102…,
    7d10629e…, 999d7f25…, 9c48f5c9…
```

Not a policy refusal — two defects in series, each isolated to one variable in
ADR 0163 and reproduced offline at zero cost:

- **F-M6-1** — `aef run --record-runs` writes `RecordedRun(...)` with no
  `model_calls`, so the determinism re-check replays against an empty cassette,
  the model call misses, and the run is rejected as non-deterministic. The
  field's own docstring predicted this failure and called it *"a correct-looking
  rejection for the wrong reason"*.
- **F-M6-2** — with the cassette supplied by hand the run is *still* rejected:
  `harvest._reexecution_services` builds `CassetteProvider(None, …)` with no
  inner provider, so ADR 0169's `prompt_agent__containment` block re-executes as
  `isolation: []`, `persona_role: 'unknown'` against a recorded `['no_mcp',
  'no_project_context', 'no_tools', 'single_turn', 'system_role']`, `'system'` —
  and the re-check compares the encoded trace byte for byte.

The three-arm isolation (`docs/research/pilot-marlin/repro_two_blockers.py`):
as shipped → rejected; + the cassette → rejected; + a provider for the re-check
→ **promoted**.

## What this says about the dimension, beyond "no change"

Dimension 7 reads *"learns from live runs and real tenants, not a synthetic
corpus; telemetry closes the loop."* Its current 4/10 is J0's (ADR 0151), whose
evidence line was:

> no live signal has ever entered harvest; the cron's `--runs` is populated by
> no step; corpus is self-generated.

J0 inferred that from reading the code. The pilot ran it, and the observation is
stronger than J0's: **the `--runs` path is not merely unpopulated, it is
unusable.** Any run of any `aef migrate`-generated prompt-agent graph — the
whole class ADR 0152 exists to serve — is refused by `harvest`, on every repo,
today, and refused with a message naming the one explanation the evidence rules
out.

So a case can be made that 4/10 is generous. **S7 does not make it**, for two
reasons that are the same reason: a worker claiming deltas on a dimension is not
the instrument that sets its base — that is J0's job, and `UPGRADE_LOOP.md` says
so ("S-workers claim deltas on dimensions; J0 may move a base") — and a worker
that can lower a base can also raise one, which is exactly the self-grading the
rubric's own first paragraph forbids. It is named here so the next independent
re-score has it in hand.

## What the loop *did* do, and why it is not worth a point here

The cycle in ADR 0163 proposed a candidate that appends one lesson bullet to
marlin's own persona, grounded in two check-derived failure records from two
real questions about Accela credentials, and the gates judged it live under
`gates.live_model_calls: true`. That is a working loop on real prompts. It is
not dimension 7, because every one of those runs was initiated by an inputs file
this process wrote: `bootstrap` is the system asking itself questions. The
dimension is about signal the system did not commission.

The distinction is not pedantry — it is the whole content of the row. A loop
that learns from questions it chose has no defence against choosing questions it
already answers well, and the trust case's criteria 1 and 6 are written against
exactly that.

It is worth recording what the gates found anyway, because it is the most
useful thing this pilot produced and it belongs to dimension 2 rather than to
7: **G3 rejected the candidate because a scenario the incumbent passed dropped
below 0.5 with the lesson in the prompt.** Not a null result — a regression, on
the task metric, from a rule-based lesson whose model excerpt ADR 0180 had
already removed. Whoever re-opens dimension 2 should start there; ADR 0163 §9
has the numbers.

## The last +3, unclaimed, with the reason

**Marlin is the owner's own repository, not a third party.** A pilot on a repo
the same owner wrote, with objectives drawn from that repo by the same process
that ran them, is real code and real prompts and it is not an independent
tenant. Dimension 7's full marks say *"live runs and real tenants"*; the tenant
half needs someone else's traffic, someone else's secrets in the redaction scan,
and someone else's judgement of whether the answers were right. Nothing in this
programme has had that, and no arrangement of this repo's own material will
produce it.

## The rubric

**Not edited.** Dimension 7 keeps J0's 4/10 and its row; the heading stays
**72 / 100**; `tests/test_rubric_arithmetic.py` recomputes the total from the
rows and is green.

A row was drafted and deleted rather than softened. The version that would have
gone in read *"real runs reached memory and the gates judged a lesson built from
them"* — every word of which is true, and none of which is the thing dimension 7
scores.

## Consequences

- The rubric's dimension-7 evidence line should, at the next independent
  re-score, cite ADR 0163's two findings rather than J0's inference.
- `UPGRADE_LOOP.md`'s M6 line ("this is the 'real signal' S7 claims +2 on") is
  superseded by this ADR: nothing is claimed.
- Whoever fixes F-M6-1 and F-M6-2 re-opens the *possibility* of (a); it does not
  by itself earn the point, because the point also needs a run the system did
  not commission.

## Confidence

**High** that the falsification fired: harvest's refusal is quoted from two
invocations on five real runs, and the cause is isolated to one variable per
arm with a passing control.

**High** that +0 is the pre-registered answer to what was observed; the branch
was written before the pilot ran and is quoted above unmodified.

**Medium** on the claim that 4/10 is now generous. It rests on this pilot's one
graph family (`aef migrate`'s prompt-agent graph), and a graph that makes no
model call at all still harvests cleanly — so the correct statement is *"no
model-calling graph"*, not *"nothing"*, and how much of dimension 7 that eats is
a judgement for the re-score rather than a measurement here.
