# ADR 0151: The independent score is the score

## Status
Accepted. BEYOND_90's J0, run as UPGRADE_LOOP's S0.

## Context

Every number in `docs/research/self-learning-rubric.md` was written by the
loop it scores. BEYOND_90 named the risk ("at 90 the remaining points are
judgement calls and the incentive to read a measurement generously is
strongest") and prescribed the control: a fresh agent, blind to
`IMPROVE_LOG.md`, every ADR, every loop file and git history, scoring
from code and tests alone — and **where it scores lower and its reasoning
is right, the lower score stands.**

It was run on `main` at 7a02f12 (1999 passed). Its report is committed
verbatim as `docs/research/j0-independent-score-2026-09-04.md`.

## The two score sets

| dim | weight | ours | J0 | resolution |
|---|---|---|---|---|
| 1 closed loop | 20 | 19 | 15 | **15** — reasoning verified, below |
| 2 what is learned | 20 | 17 | 12 | **12** — verified |
| 3 reflection | 10 | 8 | 6 | **6** — verified |
| 4 safety | 15 | 14 | 14 | 14 — agreed |
| 5 evidence | 10 | 10 | 8 | **8** — verified |
| 6 archive | 10 | 8 | 5 | **5** — verified |
| 7 real signal | 10 | 5 | 4 | **4** — verified |
| 8 adoptability | 5 | 5 | 4.5 | **4** — rows are integers; the lower integer |
| | | **86** | **68.5** | **68** |

## Every disagreement, resolved in writing

**Dim 1 (19 → 15).** J0: nothing runs the loop unattended. Verified:
`.github/workflows/loop-monitor.yml`'s daily step passes no `--memory`,
so `cmd_cycle` reaches `aef/harness/loop.py:1261` — `no memory store
configured: nothing to learn from, no candidate` — and exits 0. **This
repo's own scheduled loop has been a no-op every night since it was
written.** The adopter's rendered workflow has no cycle step at all. The
CI caches `~/.aef-loop-state` and nothing populates it. That is the exact
failure shape this repo documents at length (ADR 0139) and still had.
Reasoning right; 15 stands.

**Dim 2 (17 → 12).** J0: the experience→behaviour link is open.
Verified: `make_retrieve_node` writes `state.retrieved_context`; the only
reader in `aef/` is `aef/reasoning/nodes.py:52`, which computes
signatures for the tally; `agents/summary/graph.py::draft_node` builds
its prompt from `working_memory` alone. **The retrieved lessons reach no
prompt.** ADR 0118's "the retriever finally has a caller" was true and
insufficient — a caller that writes state nobody reads is a caller in
name (erratum appended to 0118 by S1). Consequence beyond the score:
TO_90's I12 as designed would have spent 84 calls measuring four
byte-identical arms; S1 was stopped mid-preflight and re-briefed to wire
the context into the prompt first. Reasoning right; 12 stands.

**Dim 3 (8 → 6).** J0: the judge A/B (rule 3/18, LLM 9/18) exists only as
a docstring citing an ADR; no test or script reproduces it; no judge has
been scored against a real model in-repo; no self-preference control.
Verified — I11's numbers were produced live by a worker and recorded in
prose. Under the rubric's own first rule (a score moves only on an
artifact) a measurement whose only artifact is a sentence is asserted,
not shown. Reasoning right; 6 stands. S3 re-runs it with the data
committed.

**Dim 5 (10 → 8).** J0: three shipped "off by measurement" defaults
(archive sampling, `reflection.impl: llm`, `proposer: llm`) carry their
justification only in ADRs, with no runnable script or committed data;
nothing measures the loop's end-to-end benefit. Verified. The rubric
scored 10/10 on the strength of negative results shipped as tests — and
those are real — but the three defaults that most shape the loop's
behaviour are exactly the ones whose evidence is prose. Reasoning right;
8 stands. Every S-worker in this loop commits its raw results under
`docs/research/<increment>/` so this cannot recur.

**Dim 6 (8 → 5).** J0: the lineage archive is in-memory inside one
`run_loop` call, has no CLI flag, only kept candidates enter it, nothing
persists across invocations. Verified: `grep -rn sample_parents aef/cli/`
is empty — `aef loop run` cannot enable the thing dim 6 was scored on.
Reasoning right; 5 stands.

**Dim 7 (5 → 4).** J0: no live signal has ever entered the harvest path;
the cron's `--runs` directory is populated by no step; the corpus is
self-generated. Verified and already stated in our own row ("has never run
against a real tenant"). J0 weighted it one point lower; the rule says
take it. 4 stands.

**Dim 8 (5 → 4).** J0: the Codex path's live test is one of the three
skips on the reviewer's box, and adoption leaves six manual obligations.
The first is a property of the reviewer's environment (Codex answered on
this box, ADR 0131) — but a live test that must be run by the person who
claims the point is, from code alone, an untested path, and J0 scored from
code alone by design. The second is true. J0 gave 4.5; rows are integers;
the lower integer is 4.

**What J0 missed that was discoverable: nothing.** I looked for a
dimension where evidence existed in code or tests that J0 failed to find.
Every gap it named is real; the only evidence it did not see lives in
`docs/research/` and the ADRs, which is documentation, not code — and
BEYOND_90's rule for that case is that the evidence was undiscoverable
and *that* is the finding.

## Decision

- The rubric heading is **68 / 100**, with one prepended row per lowered
  dimension citing this ADR. `tests/test_rubric_arithmetic.py` enforces
  the sum.
- UPGRADE_LOOP's S-thread deltas compose on these bases. Its "honest
  ceiling" paragraph was computed from 86 and is now wrong; the report
  recomputes it from 68 with J0's named gaps as the increments.
- Two of J0's findings become fixes tonight: the no-op scheduled cycle
  (`--memory`/`--no-memory` required, the CI step fixed, the adopter's
  workflow gains a cycle step) and the open retrieval→prompt link (S1).

## Consequences

Eighteen points, and none of them from a control failing. Every one is
the repo's own two signature shapes — *wired but not consumed* and
*asserted in prose rather than shown by an artifact* — found by someone
who did not build it. The score got to 86 by measuring components; it
falls to 68 when someone asks whether they are joined. That is the seam
finding at the scale of the whole rubric.

## Confidence

High on every resolution: each was verified by reading or running the
code the report named, not by trusting the report.
