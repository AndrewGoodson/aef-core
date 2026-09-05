# The promotion trust case

**Question this answers:** should Tier-1 auto-merge be enabled?

**Recommendation: no. Not yet, and not on this evidence.** The reasoning is in
§4; §1–§3 are what it rests on. This document was written by the same agent
that built the mechanisms it assesses, which is itself a reason to read §2
before §1.

All seven Phase-4 criteria are now implemented. **That is a different claim
from "the criteria are met"**, and the gap between those two sentences is what
this document is about.

---

## 1. Criterion by criterion

"Implemented" is not evidence. Each entry below has the mechanism, the test,
and a transcript from a run.

### 1 — Shadow execution against live traffic before promotion eligibility

`aef/harness/shadow.py`. Tests: `tests/harness/test_promotion_safety.py`.

```
  served to user      : INCUMBENT-ANSWER
  divergence recorded : fields=('working_memory',)
  candidate output in observation? False
  mutating candidate  : REFUSED — node(s) work declare side_effects=mutating…
  0 observations      : ShadowError (not 0.0)
```

The user gets the incumbent's answer while the candidate disagrees.
"Nothing it returns reaches a user" is structural: `ShadowObservation` has no
field holding the candidate's output. A divergence rate over zero observations
raises rather than reporting 0.0, so "never ran" cannot pass for "always
agreed".

**Not demonstrated: live traffic.** See §2.1.

### 2 — Null-hypothesis baseline

`G3Improvement` + `ControlCohortGenerator`. Transcript, from the six-gate run
in §1.7:

```
  G3: PASS   candidate mean 0.5 beats the control cohort's p95 of 0
```

Five random mutations of the incumbent, scored over the same corpus. The
candidate must beat their p95, not an absolute threshold.

### 3 — Golden-trace regression, never shrinks

`G2OutcomeNonRegression` + `check_never_shrinks`.

```
  G2: PASS   4 scenario(s) re-executed; every previously-passing one still passes. 0 changed routing
```

### 4 — Bounded mutation rate · ### 5 — Cumulative drift

Both in `G5RateAndDrift`, reported on pass as well as fail:

```
  G5: PASS   0/3 accepted in the last 7d; drift 0.255/0.500 from the blessed baseline
```

### 6 — Canary rollout, stratified by tenant tag, percentile-gated, warm rollback

`aef/harness/canary.py`.

```
  candidate mean 13.55 vs incumbent 10.05   (median 9.0 vs 10.0 — MEDIAN improves)
  percentile verdict  : passed=False — p99 regressed: candidate 100 exceeds 13.2 (1.20x incumbent 11)
  assignment monotone : True   full exposure at 100%: True
  retry after rollback: CanaryError — this rollout was rolled back; v2 does not climb the ladder again
  0.5% tail regression: passed=True  <-- KNOWN LIMIT
```

The regression that improves the median and destroys the tail is caught. The
last line is a limit, not a pass: see §2.2.

**Not demonstrated: real tenants.** See §2.1.

### 7 — HITL above a risk threshold · signed release manifests

`PolicyConfig.require_hitl_above_risk` (pre-existing) and
`aef/harness/release.py`.

```
  signature           : aea3d411655f325b0c589446dac89898…
  valid manifest      : verifies
  evidence swapped    : rejected
  approver swapped    : rejected
  commit swapped      : rejected
  failed-gate manifest: refused without override_reason
```

### The pipeline, end to end

A structural repair the proposer itself produced, through the real six gates:

```
  G0: PASS   1 file(s), 18 line(s), all Zone A, no static-safety violations
  G1: PASS   1 build command(s) succeeded against the merged workspace
  G4: PASS   no owner-only safety metadata declared by the candidate
  G5: PASS   0/3 accepted in the last 7d; drift 0.255/0.500 from the blessed baseline
  G2: PASS   4 scenario(s) re-executed; every previously-passing one still passes
  G3: PASS   candidate mean 0.5 beats the control cohort's p95 of 0
  DISPOSITION: ESCALATE — every gate passed, but Tier-1 auto-merge is not enabled
```

And the same pipeline on the transformation ADR 0096 shipped and ADR 0098
reverted:

```
  G0: PASS   1 file(s), 1 line(s), all Zone A, no static-safety violations
  G1: PASS   1 build command(s) succeeded against the merged workspace
  G4: FAIL   1 owner-only safety declaration(s) in agent-authored code [SECURITY EVENT]
  DISPOSITION: REJECT
```

---

## 2. The adversarial section

This section decides the document. Seven attacks were attempted against the
system as it stands. **Three outcomes are reported as they came out, including
the one that most damages criterion 1.**

```
  A1 flip Tier-1 auto-merge from config/env/flag          held
  A2 forge a manifest under a guessed key                 held
  A3 replay a valid signature onto another commit         held
  A4 shadow a node declaring EXTERNAL_CALL                BROKE IT
  A5 shadow node does file I/O directly (no tool call)    BROKE IT
  A6 choose a tenant tag that evades the candidate arm    (mislabelled — see 2.3)
  A7 reach harness code through evaluator.suites          held
```

### 2.1 The shadow's containment — bypass found, then closed

**A5 was a demonstrated bypass, not an argument.** A shadow node that opens a
file directly wrote to disk during a shadow run:

```
  A5 shadow node does file I/O directly (no tool call)    BROKE IT
```

The suppression is `PolicyEngine` with an empty scope set. That denies **tool
calls**. A node that imports `pathlib` and writes is not making a tool call.
A4 is the same finding wearing a declaration.

**It is now fixed, and the fix is verified in both directions** (ADR 0105).
`contained_candidate_graph` runs the candidate's nodes inside the Milestone 4
container — no network, read-only root — via the inverted-control worker, so
the parent still owns state and routing and a contained candidate cannot forge
an "identical" final state to hide a divergence.

```
BEFORE  — in-process shadow
  host marker written: True    <-- the bypass

AFTER   — same candidate, executed inside the container
  host marker written: False
  divergence recorded: candidate_failed='NodeEvaluationError: FileNotFoundError…'
  served to user     : incumbent state, working_memory={}
```

The read-only root is verified on paths the image really has, because the run
above is contained partly by the host path being absent — which would be
containment by accident:

```
  /etc/hosts                       OSError
  /opt/aef/aef/__init__.py         OSError
  /tmp/x                           OSError
  /aef-workspace/ok.txt            WROTE   <-- the workspace, deliberately
```

**Containment is now the DEFAULT, and it is PROVIDED rather than merely
required** (ADR 0161). ADR 0105 made `ShadowRunner` refuse to construct
without a container session, which closed the silent bypass and left the
container something every caller had to hand-build: on a box with a running
daemon and the image present, a caller that asked for nothing got the same
flat refusal as a caller with neither, and the only one-line way past it was
`uncontained=True`. Reproduced. `shadow_for` now resolves a runtime, verifies
its isolation in both directions, and returns a runner whose candidate
executes inside the container:

```
BEFORE  — ShadowRunner(incumbent, candidate) on a box WITH docker and the image
  UncontainedShadowError ... the one-line way forward is uncontained=True

AFTER   — shadow_for(incumbent, entrypoint=..., workdir=..., image=...)
  mode 'auto', contained True, isolation verified
  host marker written: False    <-- True under the old convenient path
```

`shadow.containment` has three values. **`auto` is the default and does not
fall back**: it contains the candidate, or it refuses and names which of the
runtime and the image was missing. An automatic in-process fallback would be
strictly weaker than the refusal above, so the fallback is reached only by an
owner writing `fallback` or `off` in `aef.yaml`. Every uncontained run is
announced on stderr AND written to the ledger as an `EventKind.CONTAINMENT`
entry carrying `security_event: True`, which is the key the owner's weekly
digest counts. Every observation still records which mode it ran under, one
uncontained observation still downgrades a whole report, and an AST test
allows exactly one `uncontained=True` in `aef/` — the fallback branch of
`shadow_for`, with a companion test proving the default cannot reach it.

**Two things remain, and neither is the bypass.** It requires the operator to
supply an **image with `aef` importable**, which is their build, not this
repo's; an adopter without one must state `containment: fallback` or `off` and
will see `contained=False` on every observation and a security event in the
ledger, which is the intended trade — the weaker mode stays available and
stops being invisible. And the candidate can still write to its own
**workspace**, which is a host directory: that is what a workspace is, and
containment means it cannot reach anywhere else.

Reproduce the image the tests use:

```
FROM python:3.13-slim
RUN pip install --no-cache-dir "pydantic>=2.9,<3" "pyyaml>=6.0,<7" \
    "opentelemetry-api>=1.27,<2" "opentelemetry-sdk>=1.27,<2"
COPY aef /opt/aef/aef
ENV PYTHONPATH=/opt/aef
```
`docker build -t aef-worker:test .` from a directory holding `aef/`. Without
it, `tests/harness/test_contained_shadow.py` skips rather than passing.

**And neither criterion 1 nor 6 has run against what its text names.** The
criteria say "against live traffic" and "stratified by tenant tag". Shadow was
exercised with a synthetic incumbent and candidate; the canary against sample
arrays, not tenants. What exists is a mechanism that would do those things
correctly when connected to something real. That gap is not one more test
away — it needs an adopter with traffic, and **it is unaffected by the fix
above**.

**Status update, 2026-09-05 (ADR 0163, the marlin pilot). Facts only; neither
criterion's assessment changes.** The pilot ran the whole ingestion sequence on
a copy of a real prompt-file repo — `adopt` → `migrate` → five real objectives
through `aef run --record-runs` under the real harness → `aef loop harvest` →
`bless` → `doctor` → one `cycle --cassette-miss live` → `monitor`/`digest`.
Three facts this document did not have:

1. **The ingestion path is not merely unused; it does not work.** `harvest`
   promoted **0 of 5** real recorded runs and rejected all five as "did not
   re-execute deterministically", for two reproduced defects (ADR 0163's F-M6-1
   and F-M6-2). No run of any `aef migrate`-generated prompt-agent graph is
   harvestable today, on any repo. So the sentence above — "a mechanism that
   would do those things correctly when connected to something real" — is not
   established for this path, and the pilot is the first time it was tested.
2. **The redaction step in front of criterion 6 was exercised and scanned
   clean, with a control and a named residual.** 0 substitutions and 0 output
   matches across five real runs; 5 of 5 planted credential shapes caught by the
   same policy; and the default pattern list does **not** match that repo's own
   subscription UUID, which is the identifier its boundary rules are written
   around. An adopter extends the list; the default is not sufficient for a
   tenant whose secrets are UUID-shaped.
3. **The gates did reach a live verdict on a candidate built from real
   evidence** — `live_model_calls: true`, 35 scenario executions, 30 of them
   live inside the sandbox worker, REJECT by G3 because one previously-passing
   scenario's score fell below 0.5. That is criterion 1's *mechanism* working
   end to end on a real repo; it is not criterion 1's *evidence*, because the
   runs it judged were commissioned by an inputs file rather than arriving as
   traffic, and marlin is the same owner's repository rather than a tenant.

**Neither criterion moves, and the residual-risk number is unchanged.** What
the pilot removes is an assumption: "connect it to something real and it will
work" was untested and is now known to be false for the harvest leg until two
defects are closed.

### 2.2 The canary cannot see a narrow enough regression

Demonstrated, and previously recorded as a limit rather than found by attack:

```
  0.5% tail regression: passed=True
```

p99 answers "99% are at or below this", so a regression confined to the worst
1% sits entirely above every configured percentile. I found this because a
fixture used exactly 1% and the gate passed it — the gate's coverage showing,
not a fixture bug. Adding p100 catches it, at the cost of gating on a single
worst observation.

### 2.3 An attack I mislabelled, and the real weakness under it

A6 was reported as a break and **is not one**. 1% of tenants staying on the
incumbent at 99% exposure is correct behaviour:

```
  at  50% exposure: 2501 of 5000 stay on incumbent (50.0%)
  at  99% exposure:   52 of 5000 stay on incumbent (1.0%)
  at 100% exposure:    0 of 5000 stay on incumbent (0.0%)
```

But there is a genuine weakness underneath, also demonstrated: assignment is a
public deterministic hash of the tenant tag, so **a tenant that controls its
own tag can search for the arm it wants.**

```
  tried 200 candidate tags at 99% exposure -> 1 lands on the incumbent: ['evader-106']
```

At lower exposures it is trivial.

**Now closed** (ADR 0106). Assignment is `blake2b` keyed by an owner-held
`CanarySalt`, and `CanaryState` refuses to construct without one unless
`unkeyed=True` says so — recorded on the rollout either way.

**Bounded, not eliminated, and the bound is tested.** Keying removes *offline*
computation: a tenant without the salt cannot evaluate the function, so it
cannot sift tags before choosing one. It does not remove *online* probing — a
tenant that observes its arm can re-register under new tags until it lands
where it wants, one tag at a time, visibly. Calling it unpredictable would
overclaim.

Attacking the fix found two more: the salt fingerprint was a plain digest and
so a microsecond-per-guess offline oracle (now `pbkdf2_hmac`, ~12ms measured),
and the same tenant encoded NFC vs NFD landed in different arms **52% of the
time** — one tenant, two arms, contributing to both, which is what
stratifying by tenant exists to prevent.

### 2.4 What held, and how hard it was pushed

Reported so the list is legible as evidence rather than as reassurance. A1
(no code path enables Tier-1 from config, env or flag — two references, neither
settable), A2 (forged key), A3 (signature replay onto a different commit), A7
(reaching harness code through `evaluator.suites`, the hole Milestone 2's
adversarial round found and closed). Each held under a single specific attempt.
**None was attacked by a party that did not also write the defence**, which is
the limitation §3 prices in.

### 2.5 The base rate that matters most

Six milestones in this program each ended with a mandated adversarial round.
**Every one found at least one confirmed defect** — 15 in total — in code
written hours earlier and believed correct at the time of writing:

| Milestone | Found | The worst one |
|---|---|---|
| 1 proposer | 4 | The only transformation shipped was one G4 forbids. Milestone reverted. |
| 2 config | 4 | A suite could resolve `aef.harness.loop:gate` |
| 3 interfaces | 2 | `agent_id` defaulted to *every* agent's memory |
| 4 sandbox | 2 | A timed-out container kept running — ADR 0093's defect again |
| 5 promotion | 2 | A manifest recording *failed* gates signed cleanly |
| 6 trust case | 1 | A5, above |

Across the wider program the count is ~75 defects over ~18 rounds. **The rate
has not fallen.** Three were introduced by the same session's own fixes, and
one — Milestone 1's `except HumanApprovalRequiredError` — was a *fix for a
defect found that same hour* that G4 then rejected for the same class of reason
as the defect it fixed.

Four separate times an ADR of mine asserted a property I had not checked
(0088, 0093, 0096, and `candidates_per_kind` in 0101). The shape is identical
each time: a true statement about one property, offered as the answer about a
different one.

---

## 3. Residual risk, as a number

Over **100 candidates that pass all six gates**, I would expect **5 to 10 false
accepts** — changes merged that are not improvements, including 1–3 that are
actively harmful.

**Basis, and its weakness stated first: this is derived, not measured.** No
population of 100 gated candidates exists. It is built from three components:

1. **~5 per 100 from G3's own statistics.** G3 requires the candidate beat the
   control cohort's **p95**. A candidate no better than a random mutation
   therefore clears it about 5 times in 100 by construction — that is what a
   p95 threshold means, not a flaw in it. This is the only component with a
   principled number, and it sets the floor.
2. **~1–3 per 100 from corpus blind spots.** G2 catches behaviour changes the
   corpus covers. The seed corpus is small; a regression in an uncovered path
   is invisible to it, and the harvest that grows the corpus is driven by
   failures that already happened.
3. **Unquantified: everything §2 describes.** The shadow bypass, the canary's
   narrow-regression blindness, and tag self-selection have no rate attached,
   because attempting them requires an adversary and the only one who has tried
   is the author of the defences.

**"None" would not have been an answer.** A harness whose owner expects zero
false accepts will read the first one as a bug in the harness rather than as
the rate working as designed, and will lose the ability to tell those apart.

The number to watch after enabling would be **false accepts per 100**, not
"did anything break" — and it cannot be watched without the shadow and canary
connected to real traffic, which returns to §2.1.

---

## 4. Recommendation

**Do not enable Tier-1 auto-merge.**

Four reasons, in order of weight:

1. **The two criteria whose text says "live traffic" and "tenant tag" have
   never seen either.** Criteria 1 and 6 are implemented and tested against
   synthetic inputs. Enabling on that basis would be accepting a mechanism for
   the evidence it was designed to produce rather than for the evidence it has
   produced.
2. ~~**The shadow's containment is demonstrably incomplete.**~~ **Spent.**
   The bypass is closed, verified in both directions, and containment is now
   the default rather than an opt-in — running without it is explicit and is
   recorded on every observation. This reason no longer supports the
   recommendation. It is left visible rather than deleted because a
   recommendation whose reasons quietly change is not one an owner can audit;
   three of the four still stand, and #1 was always the strongest.
3. **Every adversarial round in this program has found a defect, six for six,
   in freshly written code believed correct** — including one that revoked an
   entire milestone. There is no basis in the observed data for expecting the
   next round to be dry. An unsupervised loop is exactly the configuration in
   which the next defect is not caught by a round.
4. **This document was written by the agent that built what it assesses.** Its
   adversarial section is real and three of the seven attacks landed, but a
   list of attacks by the author of the defences is a lower bar than an
   adversary. That is an argument for an independent review, not against this
   one.

### What would change the recommendation

Not more tests. In rough order of value:

- **An adopter with real traffic**, running shadow execution for a fixed
  period, with the divergence rate published. This is the single highest-value
  missing item and it converts criteria 1 and 6 from mechanisms into evidence.
- ~~Shadow executed inside the Milestone 4 container~~ — **done**, the
  **default** (ADR 0105), and since ADR 0161 provided by `shadow_for` rather
  than hand-built, with the uncontained modes reachable only from `aef.yaml`
  and recorded in the ledger.
- ~~A keyed tenant hash~~ — **done** (ADR 0106).
- **An adversarial review by someone who did not write this**, targeting the
  four attacks that held.
- **Two consecutive dry adversarial rounds.** The program's own stopping rule,
  never yet reached.

### The narrower thing that could be enabled now

If the goal is to reduce review load rather than to remove the human, the
defensible step is **not** Tier-1. It is to keep every candidate escalating and
use the signed manifest to make approval cheap and auditable: the owner reviews
a diff and an evidence set, signs, and the signature is what merges. That keeps
the human in the loop the criteria were written to protect, and removes the
part of the work that was never the point.

**The switch is yours. I have not touched it, and no evidence I generate should
be sufficient for me to.**
