# ADR 0170: The gates could not judge a prompt

## Status
Accepted. Increment **M4c** of `UPGRADE_LOOP.md`. Model: **Opus**
(`claude-opus-5[1m]`). **Zero live model calls** — every measurement here is
offline, against `CassetteProvider` and stub providers. **No rubric dimension
moves**; what would earn one is named at the end.

ADR 0157 built a proposer that can write a prompt candidate and then measured
what happened to it:

```
G2  fail  gate raised TrustBoundaryError: scratch destination …/workspace must be empty
G3  not run — no control cohort could be built
```

so the increment landed with its own limit stated: **a prompt candidate could
be rejected and never accepted.** This ADR closes that, and a third defect
from the same list, and changes what the gates *accept* in no respect
whatsoever. The thresholds, the p95 rule, `PolicyEngine` and the Tier-1
switch are untouched; what changed is that G2 and G3 can now run at all on a
prose candidate.

---

## D1 — two gates, one scratch directory

### Reproduced

`<scratch>/repro_d1.py`: a real git repo, a real `CandidateVerdict` from
`inspect_candidate`, real `G1Builds` and `G2OutcomeNonRegression` in the real
`run_pipeline`, sharing the one `GateContext.workdir` that `loop.gate()`
gives them.

```
$ python repro_d1.py <scratch>/d1
candidate: 1 file(s), paths=['agents/persona.md']
  G1 pass  1 build command(s) succeeded against the merged workspace
  G2 fail  gate raised TrustBoundaryError: scratch destination
           …/d1/work/workspace must be empty. A gate that could not judge has
           not cleared this candidate.
REPRODUCED: D1
```

`g1_builds.py:49` and `g2_outcome.py:111` both named `ctx.workdir /
"workspace"`, and `trust._prepare_empty_destination` refuses a non-empty
destination. G2 materialises its own tree only when the driver could not hand
it a precomputed cohort — which was **every** prompt candidate (D2 below), and
also every Python candidate whose cohort failed, which is how ADR 0148 met
this message and reasonably read it as a red herring.

**It is not prose-specific.** The reproduction above uses a `.md` because that
is the shape M4 produces, but the collision is between two gates and a
directory name.

### The fix, and why not the smaller one

Each gate materialises into `ctx.workdir / f"workspace-{self.id}"`.

The tempting fix — have G2 reuse the tree G1 already built — was rejected on
what the emptiness rule actually protects. `workspace.py` states it: the
workspace is *the post-merge state*, base ref plus the candidate's Zone A
overlay and nothing else, constructed rather than checked out so the trust
boundary holds even if a zone check upstream has a bug. An empty destination
is how "and nothing else" is guaranteed. **And G1 has just run build commands
in its copy** — commands that come from repo configuration and execute
candidate code. Reusing that tree would put whatever they wrote into the tree
G2 re-executes the corpus against, which is a quiet repeal of the rule for
the one gate that runs the candidate over the corpus.

The regression test asserts exactly that, rather than the directory name: a
build command that writes `artefact.txt` leaves it in `workspace-G1` and not
in `workspace-G2`.

---

## D2 — G3 had no null hypothesis for a prompt

### Reproduced

`<scratch>/repro_d2.py`, both real call sites:

```
1. ControlCohortGenerator: ProposalError: cannot build a control cohort for
   'agents/persona.md': no module-level numeric constants to mutate, so there
   is no null hypothesis to draw from
2. CohortBuilder: SuiteError: the candidate changed no Python file, so there
   is nothing to mutate for a control cohort and G3 has no null hypothesis to
   test against
REPRODUCED: D2
```

This is **ADR 0139's requirement 2 in its final form.** 0139 measured "at
least one module-level numeric constant" by deleting one and watching the
proposer go quiet; ADR 0148 re-measured it on `migrate`'s own generated graph
and found the constant is needed by the **cohort** at least as much as by the
proposer. L6's reading was right and this is the same limit reaching the same
place from a third direction: whatever proposes the candidate, the thing that
*judges* it was built by mutating constants.

### The control that is now built

`aef/harness/prose_cohort.py`. `RuleBasedPromptProposer` appends one bullet
under `## Lessons (aef)`, so the null is:

> does appending an **irrelevant** bullet of this shape and this length, in
> this section, help as much as the real one?

Each member is the candidate with the treatment bullet's **text substituted**
for a placebo's. That is a stronger form of ADR 0054's "the cohort must use
the same machinery as the real proposal" than re-running the appender would
be: the heading, the blank lines, the insertion point and any eviction the
append performed are byte-identical to the candidate's, so the **only**
variable between a control and the candidate is the words in one bullet. The
result is still the incumbent-plus-one-bullet that `suite.py` requires — the
cohort starts where the candidate started, and no other candidate change is
carried, because `_added_bullet` refuses any candidate that made one.

The placebo is drawn from a fixed, task-neutral vocabulary, seeded from
`cohort_seed` **and the candidate's SHA-256**, so the threshold a candidate
was measured against can be re-derived from the candidate alone. It matches
the treatment's **token count** exactly.

### The alternatives, argued

**1. A lesson from another graph's memory** — the design the brief named
first. Rejected: it is not a null. `proposer.py` says what makes the numeric
cohort one — "it is what *changes that were not reasoned about* score" — and
another graph's lesson **was** reasoned about; it is merely grounded in
different evidence, and real advice can transfer. It would answer "does any
lesson help", which is a different and easier question than "does *this*
lesson help". (It is also out of reach: `CohortBuilder` has no memory store,
and giving the gate one would put another graph's records inside it.)

**2. The treatment bullet with its content words shuffled** — the brief's
second choice, and the one the evidence kills. ADR 0157's own caveat is that
the lesson which moved a scenario contained the literal string `contains
'VERDICT:'`, and the agent then emitted `VERDICT:`. A shuffle preserves every
content word, so a placebo built that way carries the treatment's active
ingredient intact. That is not a control; it is the treatment with the word
order damaged — **the exact shape the leak check refuses**, which is why that
check is load-bearing here rather than decorative.

**3. Deleting the bullet** — the incumbent, which G3 already scores
separately. A cohort of five incumbents has zero variance, so p95 collapses
onto the incumbent mean and "beats the cohort" degenerates into "beats the
incumbent": exactly the comparison ADR 0051 says proves nothing.

### The leak check

`_assert_no_leak(treatment, placebo)` raises `ProseCohortLeakError` when the
two share a content word (three letters or more, minus a stopword list). It
sits on top of a first layer that filters the neutral vocabulary against the
treatment before anything is drawn, so a vocabulary that cannot supply an
information-free bullet is a named refusal and never a quiet redraw. Both
layers are mutation-tested; the brief's mutation — *the placebo bullet carries
the real lesson's text* — trips the leak check and kills 13 tests.

Two honest limits, stated here rather than left to be found:

- The check binds on **content** words. A lesson made entirely of stopwords is
  not protected by it, and a test asserts that rather than hiding it.
- The placebo controls for the **presence, shape, position and length** of a
  bullet, **not for the plausibility of its content**. A null made of
  plausible-but-wrong lessons would be a stronger test and cannot be built
  here: generating plausible prose needs a model, and `gates/base.py` requires
  every gate to be deterministic — "a candidate's acceptance never depends on
  a model call". So a prompt edit that helps only because the agent attends to
  any confident-sounding sentence would pass this cohort, and nothing in the
  harness catches that.

### What still refuses

Scope is a lessons-section bullet append, which is the only prose edit
anything in this repo proposes. Every other shape is a named `ProseCohortError`
and G3 goes on refusing: an arbitrary persona rewrite, a candidate that
removes a bullet the loop did not write, one that adds two bullets, a new
prompt file with no incumbent version, and a candidate touching neither Python
nor a prompt file. A candidate touching **both** kinds still gets the numeric
cohort — the older and better-measured of the two — asserted by a test so the
new branch cannot capture it.

---

## D3 (ADR 0157's defect 5) — a spent call that nobody counted

### Reproduced

`<scratch>/repro_d5.py`: the real `cycle()`, the real `LLMProposer` and its
real `RuleBasedProposer` fallback; the only stub is a provider that records
being asked.

```
$ python repro_d5.py <scratch>/d5
  ledger verified: 0 entr(ies)
  the proposer produced nothing from the available evidence: agents/persona.md
  is not Python, and this proposer edits numeric constants and Python
  structure. A prompt file's proposer is --proposer rule_based_prompt.
cycle verdict: <the same sentence>
ACTUAL provider calls made: 1
cycle reported any call count: False
REPRODUCED: D5 - 1 live call spent, 0 reported anywhere
```

The rejection lived in exactly one place: the rationale of the rule-based
proposal that replaces the model's. On a prompt-file repo the fallback edits
numeric constants and a `.md` has none, so there is no rationale, and the call
goes with it. Not in the summary; not in the ledger, which a cycle that
proposes nothing never writes to; and not in `cycles.jsonl`, whose verdict is
the cycle's last line (ADR 0165).

The printed sentence is worse than silent: it says the file is not Python,
which is true and is not what happened.

### The fix

`ProposerSpend` in `llm_proposer.py` — mutable, deliberately, because a model
call is an event in time and not a function of the inputs. It is the one piece
of state in that module and it holds no influence over any proposal: nothing
reads it back, no gate sees it, and clearing it changes no candidate.

- `calls` counts **attempts**, incremented *before* the provider returns,
  because a request that errors after it was sent has still been spent. The
  number is a floor on the real cost, never an under-report.
- the rejection is recorded where it is caught, not only where it is rendered.
- `cycle` appends the note **to the "produced nothing" line itself**, not as a
  line of its own, so it reaches `cycles.jsonl` through the verdict `cmd_cycle`
  already journals. `aef/cli/` is untouched.
- `CycleRun.proposer_calls` carries the count for a programmatic reader.

After:

```
  the proposer produced nothing from the available evidence: agents/persona.md
  is not Python … [llm proposer spent 1 live model call; rejected —
  LLMProposalRejected: the reply does not parse as Python: line 3: invalid syntax]
```

---

## The whole path, offline, both verdicts

`tests/harness/test_prose_gate_path.py`. A prompt-file repo shaped like the
marlin clone: a persona in Zone A, a generated graph whose entry node is a
`PromptAgentNode` reading that persona at execution time, two recorded
scenarios carrying an owner check, a blessed baseline, and the candidate
produced by the **real** `RuleBasedPromptProposer` from two distinct failure
runs. Every model answer is a cassette entry; `cassette_miss` is the gate
default `fail`.

The cassette carries an answer for all **seven** personas — incumbent,
candidate and five placebos — because a changed prompt is a changed cassette
key, and a persona the recording never saw scores 0 as a failed node. That
coupling is asserted directly so it cannot drift silently.

### Fixture A — the treatment beats its cohort

```
summary: ran G0, G1, G4, G5, G2, G3; passed=True
evidence: 7 corpus pass(es) (14 scenario execution(s)): 1 candidate + 1 incumbent
          + 5 random control(s); 2/2 gated scenario(s) recorded from graph 'marlin-accela'
G0 pass  1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically scanned,
         no violations; 1 NOT statically scanned (not Python …)
G1 pass  1 build command(s) succeeded against the merged workspace
G4 pass  no owner-only safety metadata declared by the candidate
G5 pass  0/3 accepted in the last 7d; drift 0.138/0.500 from the blessed baseline
G2 pass  2 scenario(s) re-executed; every previously-passing one still passes.
         0 changed routing (reported, not rejected).
G3 pass  candidate mean 1 beats the control cohort's p95 of 0.5
disposition: escalate — every gate passed, but Tier-1 auto-merge is not enabled
```

### Fixture B — the treatment sits inside the cohort's spread

Identical in every respect except what the **placebos** scored: here any
bullet produces the verdict line, so the lesson's content bought nothing.

```
summary: ran G0, G1, G4, G5, G2, G3; passed=False
G2 pass  2 scenario(s) re-executed; every previously-passing one still passes. …
G3 fail  candidate does not beat the p95 of the random control cohort — this is
         the null hypothesis, not an improvement
disposition: reject — G3 rejected it: candidate does not beat the p95 of the
         random control cohort — this is the null hypothesis, not an improvement
```

Fixture B is the one that matters. A test demanding acceptance can be
satisfied by weakening G3; this one is satisfied only by G3 still binding, on
its own unmodified p95 rule.

**What these two fixtures do NOT prove.** The model is a table. They prove the
gate path reaches a real verdict on real executions of a real graph — not that
any particular prompt edit helps a real model. That claim needs live calls and
S2's noise floor (mean 0.7639, spread 0.1666 on Opus, ADR 0156) as its bar,
and `UPGRADE_LOOP.md`'s rule stands: a prompt candidate is gated live or not
at all.

---

## An existing test that had to move, and it did not

`test_controls_are_built_from_the_incumbent_not_the_candidate` inspects the
source of `CohortBuilder._control_workspaces` and asserts `_materialise_base`
appears in it and `build_candidate_workspace` does not — it guards ADR 0074's
finding that this loop's fix had once been applied to one code path and not
the other. Factoring the materialisation loop into a helper broke it.

The fix was **not** to change the test. The prose branch could have had its own
five-line copy of the loop, which would have kept the test green and recreated
the exact hazard it exists to catch. Instead the loop stays inline in
`_control_workspaces`, in one place, and both kinds of cohort feed it through
`_controls(diff, live)`. **No existing test in this repo was modified.**

---

## Green bar

`pytest -q`: **2236 passed, 5 skipped**; collected **2205 → 2241 (+36, none
removed)**. `mypy aef examples`: 133 files, clean. `ruff check .`: clean.
`ruff format --check aef tests examples`: 259 files, clean.

**Eleven mutations, eleven kills**, each restored from a `shasum -a
256`-verified byte backup with the final hash asserted equal to the pre-edit
hash (never `git checkout --`; `<scratch>/mutate.py`).

| mutation | killed by |
|---|---|
| both gates share the name `workspace` again (the defect as reported) | 2, incl. `test_g2_can_judge_after_g1_has_run_in_the_same_workdir` |
| G2 alone reverts to `workspace` | `test_g2_does_not_re_execute_in_the_tree_g1s_build_commands_wrote_to` |
| G1 alone reverts to `workspace` | the same test |
| **the placebo bullet carries the real lesson's text** | 13, incl. both end-to-end fixtures |
| the neutral pool is not filtered against the treatment | `test_a_vocabulary_made_of_the_lesson_s_own_words_is_refused` |
| the placebo does not match the treatment's token count | `test_the_placebo_matches_the_treatment_s_token_count` |
| an arbitrary persona rewrite is cohorted instead of refused | 2 refusal tests |
| a prompt candidate falls back to "no null hypothesis" again | 4, incl. both end-to-end fixtures |
| the LLM rejection is left only in the fallback's rationale | 2 |
| the call is counted only after the provider answers | 5 |
| the spend note becomes its own line instead of the journalled one | 4, incl. `test_the_spend_reaches_the_journal_verdict` |

## Consequences

- **A prompt candidate can now reach either verdict.** ADR 0157's load-bearing
  limit is closed, and closed without touching a threshold: the two fixtures
  differ only in what the *controls* scored.
- **G3's answer for prose is only as good as the placebo.** The null controls
  for a bullet's shape and length, not for its plausibility, and a stronger
  null is forbidden by the gate contract's determinism rule rather than merely
  unbuilt. That is the residual risk and it belongs in the trust case's list,
  not in a footnote.
- **D1 was never prose-specific.** Any candidate whose cohort could not be
  built died at G2 with a message about a scratch directory. That is two gates
  and a directory name, and it survived because both gates are individually
  correct and individually tested — the seam shape, for the fourteenth time.
- **The loop still cannot learn on this repo shape.** ADR 0157's other finding
  stands untouched: a failed owner check never becomes failure memory, so the
  evidence a prompt proposer runs on is not evidence a real deployment
  produces. This ADR makes the gate able to judge a candidate; it does not make
  one appear.

## No rubric change, and what would earn one

Nothing is claimed. **What would earn a dimension-2 point** is an accept
verdict on a prompt candidate scored **live**, against S2's noise floor —
which is M5's and M6's evidence to produce, on the clone, and not this
worker's. The offline fixtures here are plumbing proofs and are labelled as
such in the test's own docstring.
