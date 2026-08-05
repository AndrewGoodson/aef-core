# Overnight run 2 — morning report

**I stopped on the five-round limit, not on two dry rounds.** All five rounds
produced confirmed defects. The rate did not fall. Three of tonight's defects
were introduced by tonight's own fixes.

**One finding is unresolved by choice and needs your decision — §5.**

---

## 1. Verification table (`main` @ `326f403`)

| # | Check | Result |
|---|---|---|
| 1 | `pytest -q` | **1143 passed** (was 1011) |
| 2 | `mypy --strict aef` | clean, 97 files |
| 3 | `ruff check .` | clean |
| 4 | `ruff format --check` | 170 files |
| 5 | Vendor isolation | 7 |
| 6 | Tier-1 auto-merge OFF | 4 |
| 7 | Evolution disabled | 5 |
| 8 | Adopt kit | 91 |
| 9 | Harness | 692 |
| 10 | ADRs | 94 (was 81) |

16 commits, all merged and pushed. No branches. Table re-run green after every
merge.

---

## 2. Defects

**Every one REPRODUCED by running.** Nothing below is suspected. Grouped by
ADR; each ADR names the test that could have caught each item and says
plainly where none existed.

### Phase 1 — the decision you made (ADR 0081, corrected by 0089)
- **Removing a human-approval gate scored as a maximal improvement.** Fixed:
  a pause is its own outcome class, unforgeable by construction because only
  Zone B writes it. *(code; no test composed the two halves)*
- **Then my own fix was exploitable**: a paused scenario scores 0.0 exactly
  like a failed one, so adding `requires_human_approval=True` converted every
  regression into a G2 pass. G3's per-scenario floor caught it — defence in
  depth working — but G2 was neutralised. *(code; the test I wrote pinned the
  exploitable behaviour)*

### Phase 2 — the items you left open (ADRs 0082–0084)
- `policies`/`tools.allow` validated and were ignored; now wired, and the gate
  reads them **from the base ref** so a candidate cannot widen its own rules.
  Verified with a planted fault plus a control proving the reader isn't inert.
- `AuditLogWriter` was listed DONE with no durable writer; added, with
  argument values redacted by default.
- The adoption-sequence fixture hand-wrote the two preconditions a real
  `aef adopt` lacks — the reason five defects survived 984 tests. Pristine
  suite added alongside.
- Six deferred items, including **two open merges rolling back to the wrong
  place**, reinstating the first regression while reporting both reverted.

### Phase 3 round 1 — the worst of the night (ADRs 0085, 0086)
- **The candidate wrote the evidence that judged it.** `json.loads(stdout)` on
  a subprocess the candidate's code runs in; two lines scored a broken agent
  1.0 and passed all six gates. Stronger than ADR 0060's reward hack: there
  the agent lied, here it *authors the observation*, so the tripwire is
  compared against the forgery too. *(code; the entire evidence-production
  path was covered by source-text assertions only)*
- **G0 ran after the candidate's code executed** — the allowlist is the
  control for exactly that. *(code; ordering tests used stub gates and were
  blind to the caller)*
- A torn checkpoint **silently skipped a completed node** on resume.
  *(code; the existing test stopped one assertion short)*
- `run_id` was joined onto the checkpoint root verbatim — `../../escaped`
  wrote outside the backend.

### Round 2 (ADR 0087)
- Replay never validated the state chain: forged `scores`/`objective`/
  `checkpoint_seq` replayed clean.
- `apply` was shallow-pure and the trace record aliased live state, so a node
  could **rewrite its own history**.
- The NaN guard covered `scores` and not `working_memory`.

*All three had a test that read as if it pinned the property and asserted
something weaker.*

### Round 3 — self-attack (ADRs 0088–0090)
- **It defeated my own ADR 0085**, four commits old. I had asserted an
  exhaustive claim — "the only way" — from two tested examples.
- Two defects in decisions made earlier the same run.
- Four ways to lose a verdict: a raising gate escaping the pipeline with no
  ledger entry; a forgery filed as a parse error; replay corrupting its own
  evidence; a policy that quietly didn't apply.

### Round 4 (ADRs 0091, 0092)
- The service-wiring defect had recurred **four times**. Replaced with one
  shared list; all eight requirable services now behave identically on both
  paths.
- G3's cost rule read a number the candidate writes. Declared injection points
  with no production caller: `GateContext.tracer`, `.limits`, `domain_gates`.

### Round 5 (ADR 0093) — see §5
- **`getattr(module, "os")` defeats ADR 0088 completely.** Zero G0 findings,
  all six gates pass on a broken agent.
- `max_processes=256` → `RLIMIT_NPROC` is a **per-UID** total, so any forking
  build command failed on any machine with >256 user processes.
- The sandbox timeout killed only the direct child despite two comments
  claiming the group. **My first fix for this was a no-op**, caught only by
  running it.
- ADR 0091's default durability re-killed the state ADR 0089 made legal — the
  same shape a **fourth** time.
- A harness crash reported as *"5 previously-passing scenario(s) no longer
  pass"* because the runner's diagnostic was discarded.

---

## 3. Rounds

**Five ran. Zero dry.** Round 3 and round 5 both attacked the run's own
commits; both found that round's most severe item — as did the equivalent
round on the previous night. That is three for three.

---

## 4. What an adopting repo can now do that it could not

1. Reach a verdict from **all six gates** (G2/G3 had never run from a real
   command before this run began).
2. Satisfy all five obligations, with `aef loop doctor` reporting them at once.
3. Add a reflect node without zeroing every gate.
4. Record a tripwire and watch it halt a reward hack — exit 2, verified.
5. Run `aef loop cycle` to completion with citations in the ledger.
6. Configure `policies`/`tools.allow` and have them apply, without being able
   to widen them from a candidate branch.
7. Get a durable, redacted audit trail.
8. **Run a build command that forks** — this was broken on every developer
   machine and invisible in CI.
9. Trust that a gate which crashes still produces a verdict and a ledger entry.

---

## 5. The decision I need from you

**Static allowlisting over a shared interpreter has now failed three times,
and I stopped patching it.**

- ADR 0085 framed the evidence channel, claiming three independent layers.
- ADR 0088 found one layer false, denied the import and the attribute.
- ADR 0093 finds the attribute denial reads *syntax* while the interpreter
  offers the same reach by *string* — `getattr(m, "os")`, `vars(m)`,
  `m.__dict__`.

Each defeat came from a smaller change than the last. Adding `getattr` to the
denylist is the same move a fourth time, and I decline to record it as a fix.

The root cause is structural: **the candidate's code and the code reporting on
it share an interpreter.** Any channel the reporter can write, the candidate
can write. Options, as I see them:

- **(a) Accept it, scoped.** Keep Tier-1 off permanently, treat gate evidence
  as advisory-to-a-human, and say so in the adopter docs. Cheapest; makes the
  loop a proposal generator rather than a judge.
- **(b) Separate the processes.** Execute the candidate's graph in a child
  that has no access to the reporting channel — results crossing by a
  descriptor the child never sees, or a supervisor that observes rather than
  asks. Real work, and it is the only option that makes the evidence mean
  what the ADRs say it means.
- **(c) Contain rather than allowlist.** A real sandbox — container, seccomp,
  a separate UID — so reach is bounded by the OS instead of by an AST scan.
  `sandbox.py` already states it enforces neither network nor filesystem
  confinement.

**I recommend (b), with (a) as the honest interim** — and (a) is close to
today's posture, since Tier-1 is already off and every pass escalates to a
human.

---

## What I want you to weigh about my reliability

Across two nights I have **shipped a regression, introduced a reward hack, and
written an exhaustive security claim I had not verified.** All three passed a
green suite of 900+ tests. All three were caught only because a later round
attacked an earlier round's work.

Tonight one of my fixes was a **no-op** — I called `killpg` on a pid the
exception never carries — and only running it revealed that. That is the
method working, and it is also the fourth time this program has needed a
control to catch my own verification.

The rate of finding has not fallen across ten rounds over two nights. My
honest read is that this codebase's failure mode is seams between
individually-correct parts, that a single pass over any area is not evidence
it is clean, and that **another round of the same method will find more rather
than converge**. That is why the stopping rule exists and why I am honouring
it rather than continuing.
