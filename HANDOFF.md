# Handoff — 2026-09-08

For the next agent, whichever harness it runs in. Written by the Claude
session that took this repository from 68 to 92 on its own rubric and then
installed it on two repositories the owner actually uses.

Read this, then `AGENTS.md` (identical to `CLAUDE.md`), then
`docs/research/upgrade-2026-09-04.md`. Everything below is checkable; where
it is a judgement it says so.

---

## 1. State

- `main` is `891590b`, clean, matching `origin/main`. One worktree, one branch.
- Rubric: **92 / 100** (`docs/research/self-learning-rubric.md`). The heading
  is recomputed from the rows by `tests/test_rubric_arithmetic.py` — never
  type a total; add a row and let the test compute it.
- Green bar, all four plus the re-runner, from the repository root:

```
pytest -q                 # 3160 passed, 25 skipped, 1 xfailed
mypy aef examples
ruff check .
ruff format --check aef tests examples
make measure-ci           # every published number re-derived from committed data
```

`make measure-ci` is not optional. It re-derives the tables in the ADRs from
their committed raw data and fails on drift. It has already caught a
measurement that could not reproduce itself one increment after it was built.

## 2. The most important thing in this file

**The loop's first lesson for a real repository made that repository's agent
worse.** ADR 0204, measured by hand because the gates returned `could not
judge` when the quota ran out mid-run:

| the agent had | score on the same five questions |
|---|---|
| nothing | 0.6667 |
| a **placebo** bullet — same heading, task-neutral words | 0.8667 |
| **the lesson the loop wrote** | **0.4000** |

Two scenarios that scored 1.0000 collapsed to 0.3333 and 0.0000. The placebo
*helping* is what makes this precise: the harm is the bullet's **text**, not
its presence, not the section header, not the excerpt (ADR 0180 removed
that). Everything before this was measured on writing tasks this project
authored. The first contact with somebody's real work produced advice worse
than nonsense.

**Do not treat 92 as "ready".** It measures the machinery. The one end-to-end
result on real work is negative and reproducible.

## 3. Why it happened, and the first thing to fix

**F-Q1-1 (HIGH).** Marlin's `source-agent.md` is written for an agent **with
tools** — it reads files and calls APIs. `PromptAgentNode` runs a persona
with tools switched off (`--tools ""`, ADR 0169 measured that this genuinely
suppresses them on the Claude path and **does not** on Grok). Eight of ten
answers were tool-shaped; one **invented its own tool results** and reasoned
from them. A one-sentence addition to the persona took that to 0 of 10.

So the loop was consolidating lessons from an agent hallucinating inside a
configuration that does not match how the owner runs it. Fix this before any
further measurement of lesson quality, and the fix is a design question, not
a patch: either the node tells the persona it has no tools, or `migrate`
refuses a tool-using persona and says why, or the harness gives it tools.
Argue it in an ADR; do not pick silently.

## 4. Open findings, all reproduced, none fixed

| id | severity | what |
|---|---|---|
| F-Q1-1 | HIGH | above |
| F-Q1-3 | HIGH | `bless --graph-id X` writes one archive key, `run` uses `default`; G5 then rejects telling you to run the command you just ran, and `doctor` reports the same state `[OK]` |
| F-Q1-4 | MEDIUM | a run's `--workdir` is single-use, and the generated `LOOP.md` names one fixed path twice |
| F-Q1-5 | MEDIUM | an unlaunchable provider is reported by the gate as `3 previously-passing scenario(s) no longer pass`; `aef loop score` names the real cause |
| F-N7-1 | HIGH | `harvest._reexecution_services` hard-codes an empty memory store, so only the **first** run against a given `--memory` is harvestable (1 of 5, then 5 of 5 with the workaround) |
| F-N7-2 | MEDIUM | `digest` prints "Scenarios added: 0" from a default, and ADR 0190's "ingestion is broken" warning fired the day ingestion worked |
| F-N7-3 | LOW | the checklist asks an agentless owner to identify entrypoints two lines above saying there is no legacy code |
| F-P1-2 | MEDIUM | `doctor` says the halt channel is unset in the same minute `digest` says it is configured; `doctor` takes no `--config` and cannot read the block |
| F-P1-3 | — | G2 compares a **live** candidate against a **cassette-replayed** incumbent. On marlin, resampling alone moved the incumbent +0.2, so the comparison is biased *for* prompt candidates. An owner decision, priced in ADR 0200 |

## 5. What the owner still has to decide

1. **A third party's repository.** Five rubric points and the trust case's
   oldest criterion. Every repository measured is the owner's, one writing
   style, one set of habits; a convention all of them share is exactly the one
   none of them can reveal. One small repo belonging to somebody else is
   enough. **Nothing an agent does can substitute for this.**
2. Whether a tool-using persona should get tools, be refused, or be told it
   has none (F-Q1-1).
3. A halt notification command, if a 3am halt should reach a person.
4. Live model calls inside the gates stay an explicit per-repository opt-in.

## 6. The owner's repositories — do not touch except as described

Both installs are on branches, committed, **never pushed**, both default
branches untouched.

```
marlin        aef/adopt   17 files, 2617 insertions, main at 1b00f82
peptideindex  aef/adopt   16 files, 2691 insertions, master at 5752fcf3e
```

Undo, either one:

```
git -C /Users/raptor/marlin       checkout main   && git branch -D aef/adopt
git -C /Users/raptor/peptideindex checkout master && git branch -D aef/adopt
```

**Rules that held all week and must keep holding.** Measurement runs on a
clone in scratch, never the owner's checkout. Nothing is ever pushed from
their repositories. Files are staged **by name**, never `git add -A` — that
nearly swept two untracked directories into a commit. Nothing under
`/Users/raptor/` other than `aef-core` is written.

## 7. Hard stops

From `CLAUDE.md` and `docs/autonomy/self-improving-loop.md` §4, unchanged:

- Never enable `aef/evolution/`.
- Never weaken `PolicyEngine`, a gate's verdict logic, or a threshold to get
  a number. If a control is wrong, propose replacing it and say why.
- Never enable Tier-1 auto-merge.
- Push only this repository's `main`.
- A candidate may only ever propose to Zone A.

## 8. How work is done here

These are not style preferences; each was learned by something breaking.

- **Reproduce by running it.** A defect you have not run is a hypothesis.
  Report reproduced and suspected separately.
- **Every fix gets a mutation check.** Break the fix, watch the test fail,
  restore from a byte-verified backup (`shasum`), never `git checkout --` on
  uncommitted work. Twelve workers this week reported a mutation that
  *survived* and fixed the test rather than dropping the mutation. Do that.
- **Pre-register the falsification.** Say what result would make the claim
  false before running. Four measurements came back negative this week and
  were reported as negative; one was withdrawn after the fact when its input
  data changed underneath it.
- **A score moves on an artifact a stranger could find**, never on prose.
- **Two measurement branches must not touch one corpus.** Check
  `git merge-base --is-ancestor` before trusting a row. This cost a
  withdrawn result.
- **Stale bytecode has hidden a same-length edit three separate times.** Use
  `PYTHONDONTWRITEBYTECODE=1` when mutating.
- `python` must be on `PATH` or the build gate rejects every candidate before
  it can be scored — one worker produced a whole false result that way.
- In command chains: `set -eo pipefail` and an explicit `rc=${pipestatus[N]}`
  check before anything irreversible. A pipe to `tail` swallowed a failing
  exit code and pushed a red suite once.

## 9. Where the evidence is

- `docs/research/upgrade-2026-09-04.md` — the whole programme, three waves.
- `docs/adr/` — 0151 to 0204. Read `README.md` there first; every design
  choice has a written rationale and several carry errata where a later round
  proved the ADR wrong.
- `docs/research/marlin-live/` — the run described in section 2.
- `docs/research/pilot-peptide/`, `night-1/`, `i12*/`, `i13/`, `i14*/`,
  `j2*/`, `j4/` — every measurement's runner and raw data.
- `tests/adversarial/` — 18 attacks, each with a mutation proving its control
  is load-bearing. `pytest -m adversarial`.

## 10. If you want a next increment

In the order I would take them:

1. **F-Q1-1**, because every lesson-quality measurement is downstream of it.
2. **Re-measure the marlin bullet after that fix.** The negative result in
   section 2 is the only end-to-end result on real work; it deserves a second
   reading rather than a rationalisation.
3. **F-N7-1**, which silently throws away four fifths of any real repository's
   harvestable runs.
4. The rest of section 4, cheapest first.

Do not chase the last eight rubric points. Five need a third party and three
are more of what is already measured. The number is not the work.
