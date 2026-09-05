# ADR 0157: A lesson appended to a prompt

## Status
Accepted. Increment **M4** of `UPGRADE_LOOP.md`. Model: **Opus**
(`claude-opus-5[1m]` for the harness calls; the model authorisation is stated
in `UPGRADE_LOOP.md`). **15 live calls** (budget ≤ 30). **No rubric dimension
moves** — see "What would earn a point" below.

## Context — the reproduction, and it is not the one the brief predicted

On a copy of the marlin clone, `aef migrate` (8 graphs), two bootstrap inputs
for `marlin-accela` recorded with `--memory` and `--config aef.yaml`, one of
them carrying an owner check the persona does not satisfy:

```json
{"path": "working_memory.prompt_agent", "op": "contains", "value": "VERDICT:"}
```

An honest check, not a rigged one: the objective is a plain domain question
("may the connector be enabled for Clearwater?"), and the owner wants every
answer to end with a machine-readable verdict line the ingestion runbook can
parse. The persona never says to emit one. `aef loop score` confirms the
scenario fails and the other passes, from the cassette, with no live call:

```
task metric — agents.migrated.marlin_accela.graph:build_graph (marlin-accela) — repeat=1
  model calls: 2 cassette hit(s), 0 miss(es), on_miss=fail — replayed
  train       n=2   with_checks=2   mean=0.5000 stdev=0.7071 ci95=[-0.4800, 1.4800]
      0.0000  accela-missing-credentials
      1.0000  accela-preconditions
```

Then the cycle the brief predicted would print `the proposer produced nothing`:

```
$ aef loop cycle --proposer rule_based --agent-root .claude/agents \
    --agent-path .claude/agents/accela-agent.md --memory <the bootstrap file> \
    --config aef.yaml --cassette-miss live ...
  ledger verified: 1 entr(ies)
  no admissible failure memory: no candidate this cycle
cycle verdict: no admissible failure memory: no candidate this cycle
```

**It never reached the proposer**, and the reason is a layer below M4's brief.
`make_reflect_node` writes `kind="failure"` iff `failure_signals(state)` is
non-empty, which reads `state.errors` and `state.tool_results`. An owner
**check** is the task metric (ADR 0113) and is evaluated by the harness *after*
the run; it never touches `state.errors`. And a node that raises reaches
`state.errors` only if it declares `fallback_node_id`, which
`make_prompt_agent_node` does not. So:

> **A prompt-file agent that answers cannot produce failure memory.** Both
> bootstrapped runs wrote `kind="success"`, with
> `verbal_feedback: "no failure signals: 0 error(s) recorded, 0 tool call(s),
> none failed"` — including the run that failed the owner's check.

That is the honest state of the wire from the score to the proposer, and it is
recorded here rather than worked around: the loop is silent on exactly the repo
shape M1 made runnable.

## Decision

### 1. `RuleBasedPromptProposer` — `aef/harness/prompt_proposer.py`

Same protocol as the other two (`propose_from_memory(evidence, *, proposal_id,
path, source)`), so `_build_proposer` hands `cycle` any of the three.

- **Evidence**: the admissible records `MemoryEvidence` already filtered
  (validation/holdout-derived records are gone before this module sees them),
  minus records whose `run_id` belongs to *another graph's* scenario. That
  filter uses `MemoryEvidence`'s own rule — deny what is known to be another
  graph's, admit a run id the corpus has never heard of, because that is
  production experience.
- **Lessons**: the admissible records are consolidated through
  `RuleBasedConsolidator`, not through a second copy of its rules. The two-run
  threshold (ADR 0110), one-representative-per-run, `runs_since_last_seen`
  (ADR 0116) and the helpful/harmful tallies (ADR 0118) are therefore the
  measured ones. Entries are ordered by recurrence, then recency, then
  signature — one stable total order.
- **The bullet**: the highest-recurrence entry not already present, rendered as

  ```
  - <!-- aef sig=failure:prompt_agent runs=2 --> <the recorded feedback, verbatim>
  ```

  under a `## Lessons (aef)` section at the end of the persona, created if
  absent. Two transformations are applied to the text and both are stated in
  the code: newlines collapse to spaces (a bullet is one line) and the result
  is capped at `MAX_BULLET_CHARS = 400`. Nothing is paraphrased and **no model
  is called** — ADR 0110's rule, that the model may write prose and never a
  counted field, is met here by there being no model at all.
- **Never rewrites an existing bullet.** Lines are copied byte-for-byte; the
  only line ever removed is an evicted one. At `max_bullets` (default 5) the
  stalest bullet *this loop wrote* is evicted, ranked by
  `runs_since_last_seen` looked up live from the current records; a signature
  the records no longer support ranks stalest of all, ties break to the
  earliest bullet. **An owner-written bullet is never evicted** — if owner
  bullets fill the section the proposer proposes nothing and says so.
- **Zone A or a named refusal.** `PromptOutsideZoneAError` for any path the
  gates' own `ZonePolicy` does not classify Zone A (ADR 0147/0152), raised
  rather than returned, because a proposer aimed at the harness is a
  configuration to fix and not a quiet cycle. A path that is not `.md`/
  `.markdown`/`.txt` proposes nothing and names `--proposer rule_based`.
- **Idempotent.** Same evidence → same bytes; a second cycle over the same
  evidence finds the lesson present and says which one. A second *distinct*
  lesson is appended when the store holds one — the alternative, stopping at
  the single top entry forever, would make the bullet budget unreachable.

### 2. Why it explains itself: `no_proposal_reason`

`cycle` printed `the proposer produced nothing from the available evidence`
for at least four different situations. The proposer now carries an optional
`no_proposal_reason(evidence, *, path, source)` hook — read with `getattr`, so
the two older proposers need no change and `proposer.py`'s definition of what
a proposal *is* is untouched — recomputed rather than remembered, so the
proposer stays frozen and deterministic. When no hook exists and the agent
path is not Python, `cycle` says so and names the proposer that fits. That
sentence is what turned the `--proposer llm` arm below from a silent nothing
into a diagnosable one.

### 3. It is nobody's default, and the reason is stated

M4 asks whether a graph whose entry node is a `PromptAgentNode` should default
to this proposer. **It does not, because the node kind is not cheaply
knowable at the decision point:** `Node` carries no kind field;
`_build_proposer` receives a `LoopConfig` and never a `Graph` (`cycle`'s
`graph=` is optional and exists for `harvest`); and matching on the node id
`"prompt_agent"` is a convention the generated module happens to use, not a
fact about the agent. The only signal in reach is the agent path's suffix,
and switching proposers on a filename would make `--proposer` mean different
things in different repos — the loop's own rule that widening is a decision,
not a default. An owner names it; the CLI help and the empty-cycle line both
say which one to name.

## Measurements — L4, and 15 live calls

Quota preflight (ADR 0150's corrected argv): `is_error: false`,
`result: "OK"`, `usage.input_tokens: 2`, model `claude-opus-5[1m]`. Proceed.
**1 call.**

Bootstrap of the two inputs: **2 calls.** Reproduction cycle: **0.**

### The L4 table — same repo, same failing scenario, one cycle each

`--cassette-miss live --config aef.yaml`, agent path
`.claude/agents/accela-agent.md`, Zone A `.claude/agents`,
`--build-command "python -m compileall -q agents"` (see the note below).

| | `--proposer rule_based_prompt` | `--proposer llm` (`claude-opus-5`) |
|---|---|---|
| candidate produced | **yes** (`cycle-…-prompt`) | **no** |
| lines changed | **4** (`+4/-0`, one file) | — |
| G5 drift consumed | **0.007 / 0.500** | not reached |
| G0 | **pass** — 1 file, 4 lines, all Zone A; 0 Python scanned, 1 not Python | not reached |
| G1 | **pass** — 1 build command against the merged workspace | not reached |
| G4 | **pass** — no owner-only metadata declared | not reached |
| G5 | **pass** — 0/3 accepted in 7d, drift 0.007/0.500 | not reached |
| G2 | **fail** — `TrustBoundaryError: scratch destination …/workspace must be empty` | not reached |
| G3 | **not run** — no control cohort could be built | not reached |
| disposition | **reject** (G2 could not judge) | no candidate; nothing gated |
| live calls | **0** | **1** (the model answered; the reply was discarded) |

The `llm` arm's model call is not visible from the cycle output, because the
fallback swallows the rejection whenever the fallback itself proposes nothing.
Re-run through the same construction to capture it — **1 more call**:

```
REJECTED LLMProposalRejected: the reply does not parse as Python: line 16:
  invalid character '—' (U+2014)
```

**ADR 0122's finding, restated for prose: `LLMProposer` cannot propose a
prompt at all.** Not because the edit was too large — G5's budget was never
reached — but because every validation it performs is a Python validation
(`ast.parse`, G0's import scanner, G4's declaration check). One live call per
cycle, spent, discarded. The drift budget was **not** raised (the second
falsification named in the brief did not fire, because the arm never produced
a diff to measure).

### Did the lesson change behaviour? — paired, all live

The gates never scored the candidate live (G2 could not judge; G3 had no
cohort), so this was measured directly with `aef loop score --cassette-miss
live` against a **cassette-stripped copy of the corpus**, so both arms are
live and neither replays. Per-scenario, paired, `repeat=1`, run twice:

| scenario | incumbent (live) | candidate (live) | run 2 |
|---|---|---|---|
| `accela-missing-credentials` | **0.0000** | **1.0000** | same both arms |
| `accela-preconditions` | 1.0000 | 1.0000 | same both arms |
| mean (n=2) | **0.5000** | **1.0000** | identical |

**4 + 4 = 8 calls**, plus the 2 of an earlier candidate-only pass that is
superseded (it scored the incumbent from its cassette, which is a replay, not
a paired live read — kept in the count, not in the table). **15 total.**

The first falsification — "the lesson reached the prompt and did not change
behaviour" — **did not fire**. The scenario the owner's check failed now
passes, twice, live, and the flip is a binary check outcome rather than a
mean nudged inside S2's noise floor (mean 0.7639, spread 0.1666 on Opus).

**And the caveat that matters more than the result.** The lesson's text is the
critic's rendering of the failure, and the failure this ADR had to synthesise
(see below) *names the check*: the bullet appended to the persona contains the
literal string `contains 'VERDICT:'`. The agent then emitted `VERDICT:`. That
is ACE's method working exactly as described — feedback from a failed attempt,
appended to the context — and it is also **teaching to the test**, and nothing
in the loop distinguishes the two. A lesson derived from a check carries the
check's own answer. Stated here because a +0.5 on a metric whose target string
was pasted into the prompt is not evidence that the agent got better at
anything else.

### The evidence was synthesised, and how

There is no producer of failure memory on this repo shape (the reproduction
above). The two failure records the L4 arms consumed were therefore written by
the **real** `make_reflect_node` + `RuleBasedCritic` + `FileMemoryStore` over
an `AEFState` carrying the check failure as `state.errors[0]` — i.e. exactly
what the reflect node would have written had the check outcome been wired into
the run. Two distinct runs: the bootstrapped scenario id, and a later
production-shaped run id the corpus has never heard of. **The records are
synthetic in origin and real in shape; the candidate, the gates and the live
scores are real.** `<scratch>/make_evidence.py` is the script and says so in
its own docstring.

## Defects found outside this worker's files — reported, not fixed

1. **G2 can never judge a non-Python candidate.** When the control cohort
   cannot be built, `G2Outcome` falls back to materialising
   `ctx.workdir/"workspace"` itself — the same path `G1Builds` already
   materialised in the same cycle — and `trust._prepare_empty_destination`
   refuses a non-empty destination. Result: `TrustBoundaryError` on every
   prompt candidate that gets past G1. (`aef/harness/gates/g2_outcome.py:111`,
   `aef/harness/gates/g1_builds.py:49`.)
2. **G3 has no null hypothesis for a prompt candidate.** The harness says so
   itself, well: *"could not build evidence (the candidate changed no Python
   file, so there is nothing to mutate for a control cohort and G3 has no null
   hypothesis to test against)"*. `ControlCohortGenerator` mutates module-level
   numeric constants; a `.md` has none. **A prompt candidate can therefore be
   rejected but never accepted**, and that is the load-bearing limit on M4's
   whole increment. A control cohort for prose (perturbed bullets? a shuffled
   lesson?) is a design question, not a patch.
3. **`aef migrate --agent-root .claude/agents` prints an unimportable run
   command.** `aef run .claude.agents.migrated.marlin_accela.graph` →
   `TypeError: the 'package' argument is required to perform a relative
   import`. A hidden directory is not an importable package path. This
   measurement therefore keeps the generated graphs at the default `agents/`
   root (importable) and passes `--agent-root .claude/agents` to the loop, so
   Zone A still contains the personas. (`aef/cli/migrate.py`.)
4. **`aef loop bless` accepts a `--state` inside the repository; `aef loop
   cycle` refuses it** with a good reason ("the audit trail would be part of
   what it audits"). One of the two is wrong. (`aef/cli/loop.py::cmd_bless`.)
5. **A live call the `llm` proposer spends is invisible when the fallback
   proposes nothing** — the rejection is attached to the fallback's rationale,
   and there is no fallback proposal on a `.md`. (`aef/harness/llm_proposer.py`.)

Also observed, not a defect of this repo: the pilot's own default G1 command
(`python -m pytest -q`) exits 2 with **13 collection errors** on the base ref,
before any candidate — hence the `--build-command` above. G1 was measured
against a command the pilot's environment can actually run, and that command
(`compileall` over the generated graphs) is a weak build bar; it is named so
nobody reads G1's `pass` as more than it is.

## No rubric change, and what would earn one

Nothing here is claimed on the rubric. **What would earn a point on dimension
2** is a prompt candidate that reaches an *accept* verdict on a gate that
actually executed it — which needs defect 1 fixed and defect 2 answered, and
neither is this worker's file. **What S1's wiring changes** is upstream of
that: S1 is putting retrieved context into the prompt (`aef/reasoning/nodes.py`
+ `agents/summary/graph.py`, ADR 0151's second gap). When it lands, a lesson
can reach a run through *retrieval* — per-run, budgeted, reversible — as well
as through this proposer's *durable* edit to the persona. They are different
instruments and the difference is worth measuring rather than assuming: a
retrieved lesson costs context every run and disappears when the store
forgets it; an appended bullet is permanent, gated once, and visible in a
diff. If S1's arm moves the same scenario, the honest reading is that the
prompt edit bought persistence rather than capability, and the +1 belongs to
whichever instrument is measured against the other — not to both.

## Green bar

`pytest -q`: **2163 passed, 5 skipped**; collected **2136 → 2168 (+32, none
removed)**. `mypy aef examples`: 132 files, clean. `ruff check .`: clean.
`ruff format --check aef tests examples`: 254 files, clean.

Six mutations, six kills, each restored from a `shasum -a 256`-verified byte
backup (never `git checkout --`; final hash asserted equal to the pre-edit
hash):

| mutation | tests that failed |
|---|---|
| count records, not distinct runs (drops the two-run rule) | `test_two_records_in_one_run_are_still_one_occurrence` |
| propose the top lesson even when it is already in the prompt | 2, incl. `test_the_same_evidence_twice_proposes_the_bullet_once` |
| evict the freshest bullet instead of the stalest | 2 eviction tests |
| a non-Zone-A path is a quiet no-op instead of a named refusal | both Zone tests |
| drop the provenance marker from the bullet | 10 |
| learn from every graph's runs, not this one's | `test_another_graphs_scenario_is_not_this_prompts_evidence` |

## Erratum (ADR 0170, 2026-09-04) — defects 1, 2 and 5 are closed

Three of the five defects reported above were fixed by worker M4c, each
reproduced first:

- **Defect 1** (G2 re-materialises the workspace G1 built). Both gates named
  `ctx.workdir / "workspace"`. Each now materialises into
  `workspace-{gate id}` — a directory per gate rather than a shared tree,
  because G1 has already run build commands in its copy and the emptiness rule
  is what guarantees a gate runs against base-ref + Zone A overlay and nothing
  else. **It was never prose-specific**: any candidate whose cohort could not
  be built died the same way.
- **Defect 2** (no null hypothesis for a prompt candidate). `aef/harness/prose_cohort.py`
  builds one: length-matched placebo bullets in the same section, drawn from a
  task-neutral vocabulary, refusing any placebo that shares a content word with
  the treatment. The sentence above — *"a prompt candidate can therefore be
  rejected but never accepted, and that is the load-bearing limit on M4's whole
  increment"* — no longer holds: both verdicts are demonstrated offline in
  `tests/harness/test_prose_gate_path.py`, with G3's p95 rule and every
  threshold unchanged. This ADR's caveat about **teaching to the test** is what
  made the word-shuffle placebo unusable, and is quoted in 0170 as the reason.
- **Defect 5** (a live call the `llm` proposer spends is invisible when the
  fallback proposes nothing). `ProposerSpend` counts attempts and carries the
  rejection; the note is appended to the line `aef loop cycle` journals, so it
  reaches `cycles.jsonl`.

**Defects 3 and 4 are still open** (`aef migrate --agent-root .claude/agents`
prints an unimportable run command; `bless` accepts a `--state` inside the
repository that `cycle` refuses). The L4 table above is left exactly as
measured — it is the record of what the gates did on 2026-09-04, and the ADR
that changed the answer is 0170.

## Consequences

- A prompt-file repo has a proposer that can write a candidate. Whether that
  candidate can ever be *accepted* is a gate question this ADR does not close,
  and defect 2 is the reason.
- The loop's silence on a prompt-file repo has two causes, and only one is
  fixed here. The other — that a failed owner check never becomes failure
  memory — is a wire nobody owns yet, and until it exists the proposer runs on
  evidence a real deployment does not produce.
- A lesson computed from a check contains the check. That is the honest cost
  of ACE's method against a metric written as a string match, and it argues
  for checks that describe outcomes rather than tokens.

## Erratum (ADR 0174, worker M4b)

Two sentences above are now out of date, and both were this ADR's own
"Undone".

**"That a failed owner check never becomes failure memory — is a wire nobody
owns yet, and until it exists the proposer runs on evidence a real deployment
does not produce."** The wire exists: `aef/harness/check_memory.py`, wired into
`aef loop bootstrap`. The reproduction quoted at the top of this ADR was re-run
offline and then live, and it now ends `1 FAILED AN OWNER CHECK … 1 of them
is/are a check-derived FAILURE record`, two such runs consolidate to one
`KnowledgeEntry`, and the cycle that printed `no admissible failure memory`
proposes a candidate the gates reach a verdict on. **The evidence for a prompt
candidate is no longer synthesised**; `<scratch>/make_evidence.py` describes how
it was done before a producer existed and is superseded.

**"A lesson derived from a check carries the check's own answer … nothing in
the loop distinguishes the two."** The producer's rendering never reads
`check.value`: the bullet the same pilot now produces says *"working_memory.prompt_agent
does not contain a required substring the owner declared; observed 406 words,
2836 chars: '…'"* where this ADR's said ``contains 'VERDICT:'``. Two tests grep
the whole record and the rendered prompt for a planted literal. **The caveat is
narrowed, not retired**: ADR 0174 §4 lists four things the lesson still leaks —
the state path, the operator (which for an `equals` check on a binary field
leaks the answer completely), the observed value, and the pass/fail counts. What
is now true is only that a lesson cannot be satisfied by pasting a string out of
itself.

Unchanged: **defects 1 and 2 above reproduce exactly** — G2 still raises
`TrustBoundaryError` on every non-Python candidate that clears G1, and G3 still
has no null hypothesis for a `.md`, so a prompt candidate can still be rejected
and never accepted. The L4 table's live flip (0.0 → 1.0) is **not** re-claimed
under the new rendering and has not been re-measured.


## Erratum (2026-09-05, ADR 0178, fix wave J2)

**`--agent-path <persona>.md` is documented here and under `--proposer`, and
was documented nowhere the flag's other reader could see it.**

§1's reproduced invocation is
`--agent-path .claude/agents/accela-agent.md`, and `--proposer`'s help says
`rule_based_prompt: for a `.md` prompt-file agent (--agent-path <persona>.md)`.
The four `--agent-path` arguments on `cycle`, `run`, `bless` and `doctor`
carried **no help text at all**, so the only written record of the second
meaning lived under a different flag — and `aef/harness/preflight.py`, which
reads the same flag, understood only the first. Every prompt-proposer cycle
therefore printed `reflect node routed to: no reflect node in the graph`
about a graph that routes correctly, and reported obligation 6 green over a
planted invisible model call (reproduced, ADR 0178).

Nothing about the proposer changes: it still receives the persona and still
appends its lesson to the `.md`. What changed is that the flag now carries
help text naming both forms on every subcommand that takes it, derived from
one string, and that preflight resolves the persona to its generated graph
before asking a question about Python.
