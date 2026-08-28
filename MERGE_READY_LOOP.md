# Loop prompt — get green and merge-ready, two tracks

Paste after `/loop`. Two independent tracks in two repos. **Run one increment
from one track per iteration, then stop.** Track A first unless told otherwise:
it is short, it is nearly done, and it ends in a decision you can act on.

---

## Standing boundaries (both tracks, non-negotiable)

- **Never commit to `main`** in either repo. Never `git add -A` in Raptor —
  it carries 280+ uncommitted entries including live scheduler state.
- **No restarting the daemon or API**, no deleting data, no deleting DB rows.
  Those are owner actions and their absence is not a blocker you may route
  around.
- **No green test without a passing mutation check.** Perturb the production
  value the test claims to assert, confirm it fails, revert, confirm it passes.
- **Verify every failure count with a full `grep -c`, never a truncated
  `tail`.** A tail-truncated read produced a false progress claim once already.
- **Check what your patch actually changed, not just that the count moved.**
  Three separate mutations in this program hit the wrong line and read as
  detections. `git diff` does NOT report untracked files — it is not a revert
  check for a file git has never seen; diff against a backup copy instead.
- Report reproduced and suspected separately. Never blur them.

Agents to use rather than doing everything inline: `seam-hunter` for joins
between components that are each individually correct, `Explore` for locating
code, `general-purpose` for parallel measurement fan-outs. Launch independent
agents in one message so they run concurrently.

---

# TRACK A — aef-core: `wikiskill/knowledge-layer` → merge-ready

**State: already green.** 1558 tests, `mypy aef examples` clean on 118 files,
`ruff check` and `ruff format --check` clean. Six commits ahead of `main`,
nothing merged. The work here is NOT fixing red; it is closing the gap between
"the tests pass" and "an adopter can actually reach this".

Green bar before every commit, all four:

```
pytest -q ; mypy aef examples ; ruff check . ; ruff format --check aef tests examples
```

Note `mypy aef examples`, not `mypy aef` — that is what CI runs, and the
narrower command was used throughout the build.

### A1 — the config path cannot reach the layer. This is the real blocker.

`aef/config/factory.py::build_retriever` takes `memory=` and has **no
`knowledge=` parameter**, so a `MemoryRetriever` built from an `aef.yaml` can
never receive a knowledge store. `ContextConfig` has no field for it either.

The capability is therefore reachable only by hand-constructing `Services` in
Python. **That is the exact defect shape ADR 0101 deleted `GraphStore` for** —
"a slot no code fills and no config can configure is a promise" — and shipping
it would re-commit the error that ADR exists to record.

Fix it or document it as deliberate; do not leave it unstated. If fixing:
`build_retriever` takes the already-built store for the reason its docstring
gives (two constructions of one dependency drift, ADR 0091) — the knowledge
store must arrive the same way, not be constructed inside. Check whether
`agent_services` and the config path can disagree about which store the
retriever reads versus which the consolidate node writes; **that disagreement
would retrieve nothing and look like an empty wiki.** Prime candidate for
`seam-hunter`.

### A2 — no example graph uses it

`grep -rl "consolidate\|knowledge" examples/` returns nothing. CI type-checks
`examples/`, so an example is also a compile-time check that the public API is
usable as documented. Decide: add a worked example, or state in the ADR that
the layer ships without one and why.

### A3 — the onboarding surface never mentions it

`AGENT_INTEGRATION.md` has zero mentions. `docs/roadmap.md` mentions "knowledge"
only in the context of the DELETED `GraphStore`, so a reader of the
authoritative real-vs-stubbed document would conclude no knowledge layer
exists. `aef adopt`'s generated files (`aef/cli/`) do not mention it either.

CLAUDE.md is currently the only place the layer is described. Per this repo's
own rule that the roadmap is "the authoritative, currently-accurate answer",
roadmap.md is the one that must not stay wrong.

### A4 — adversarial round before merge

Every adversarial round in this program found a defect, **six for six**, in
freshly written code believed correct. This layer has had five increments of
planted faults but no independent hunt. Run `seam-hunter` over the joins
specifically:

- `Services.knowledge` ↔ `agent_services` ↔ `_suppressed_services` (one drift
  here already shipped and was caught by an existing guard, not by me)
- consolidate node ↔ reflect node ordering — the node reads what reflection
  wrote, and placed before it simply consolidates without this run's record,
  with no error
- retriever's `knowledge_min_occurrences` ↔ consolidator's `min_occurrences` —
  two independent thresholds; one already masked a planted fault in the other
- knowledge store ↔ checkpoint/replay: entries are NOT in `AEFState`, so what
  happens on resume is untested

Report findings; do not fix them in the same increment.

### A5 — the merge recommendation

Write it as a document with evidence, not a verdict. State what is measured
(the I4 coverage table, the I5 negative result), what is unmeasured (the layer
has never run against a real adopter graph or a live model), and what an owner
is deciding. Recommend for or against, and say which finding would change the
recommendation. **"Recommend against" is a legitimate output.**

Track A is done when A1–A5 are each closed or explicitly deferred in writing.

---

# TRACK B — Raptor: `green/test-inventory` → green

**State: not green, and the number is known.** Repo `/Users/raptor/Raptor`,
branch `green/test-inventory`, 37 commits ahead of `raptor-fix`. Read
`HANDOVER.md` first — it is self-contained and current.

```
files 1-325:    384 -> 190     (28 of the 190 are untracked files)
files 326-650:  497 -> ~390    (82 untracked)
files 651-1060: NEVER MEASURED
```

Scoped pytest only. **Never a full-suite sweep, never above `-n 2`** — `-n 6`
drove this box into memory pressure severe enough that the guard ran
`launchctl bootout com.raptor.daemon` and stopped the live trading daemon.

### B1 — measure the unmeasured third, before fixing anything

Files 651-1060 have never been counted. Any claim about "how far from green"
is currently an extrapolation over a third of the suite. Fan out with
`general-purpose` agents over disjoint file ranges, `-n 2` each, and produce a
per-file failure count with `grep -c`. Split tracked from untracked — untracked
files inflate every baseline and are not repo debt.

### B2 — classify before grinding

The dominant remaining category is **tests targeting paths production
deliberately closed**, and no amount of fixing touches it:

- **VOL-3383** — `StrategyFactory.screen()` refuses direct calls. Blocks 5 in
  `test_factory_async_cycle_vol1660b`, plus 12 in `test_daemon_workers`.
- **Candlestick guard** — `pre_emission_screen.py:427` drops candlestick
  blueprints from unsanctioned sources; blocks the last 7 of
  `test_idea_processor`.
- **Removed startup contract** — `test_alpha_factory_daemon_startup_memory`
  targets `_run_*` wrappers that were inlined.

Each needs someone who knows the intended contract. **Produce the list and stop
— do not guess the contract.** A test rewritten to match whatever the code
happens to do now is a test that defends the current behaviour whether or not
it is right.

### B3 — fix, one file per iteration

Heaviest tracked, non-blocked file first. Mutation check every fix. Commit
separately with the mutation evidence in the message. If a fix mutation-checks
as inert, **revert it and say so** — three changes were reverted this way
already, and each revert was worth more than the change would have been.

### B4 — the owner-blocked items, restated each iteration

Not agent work. Do not attempt, do not route around, and do not report the
branch as green while they are open:

- Restart the API so `GET /api/manifest/column-occupancy` stops 404ing.
- Restart the paper loop so the `execution_sizer.py` full-size-equivalent cap
  takes effect in a live process.
- Ratify the four market-semantics numbers in `FX_REMOVAL_PLAN.md` (ES
  tradeable hours, intraday exit, correlation groups, VX session timezone).
- Decide the disposition of the 2 untracked test files.

---

## Each iteration, either track

1. Say which track and which item, and what you expect before running anything.
2. Build, run, measure. Full `grep -c` counts.
3. Green bar (Track A: all four; Track B: scoped pytest for the touched files
   plus a stash-and-diff zero-new-failures proof).
4. Commit small, conventional message, mutation evidence in the body.
5. Append expectation/measurement/verdict to `WIKISKILL_LOG.md` (Track A) or
   `FLOOR_OBS_LOG.md` (Track B).
6. Stop. One increment per iteration.

**A track is finished when its own items are closed — not when it feels done.**
Say plainly which items remain and which are owner-blocked.
