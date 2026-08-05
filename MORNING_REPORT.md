# Overnight run — morning report

**I stopped on the five-round limit, not on two dry rounds.** Every one of the
five rounds produced confirmed defects. The rate did not fall. Per the
stopping rule you set, that means the approach has plateaued and needs you.

---

## 1. Verification table (current, `main` @ `a176737`)

| # | Check | Result |
|---|---|---|
| 1 | `pytest -q` | **1011 passed** (was 907) |
| 2 | `mypy --strict aef` | clean, 96 files |
| 3 | `ruff check .` | clean |
| 4 | `ruff format --check` | 160 files formatted |
| 5 | Vendor isolation | 7 passed |
| 6 | Tier-1 auto-merge OFF | 4 passed |
| 7 | Evolution disabled | 5 passed |
| 8 | Adopt kit | 83 passed |
| 9 | Harness | 609 passed |
| 10 | ADRs | 81 (was 72) |

7 commits, all merged and pushed to `main`, no branches left.

---

## 2. Defects

**About 45 confirmed tonight, every one REPRODUCED by running** — none is
"suspected". Grouped by ADR; each ADR names the test that could have caught
each item, and where none existed, says so.

### ADR 0073 — the five obligations contradicted each other (3 + 1 near-miss)
- **Obligation 5 was unmeetable**: `LOOP.md` told owners to archive a blessed
  baseline and **no command existed**. G5 refused every candidate forever.
  *(code; no test could have caught it — nothing tested the obligation as a whole)*
- **Obligation 2 made obligation 3 impossible**: every reflect node needs
  `critic`/`judge`; `aef run` wired neither, so satisfying one documented
  requirement broke another. Same omission broke obligation 1. *(code; none)*
- `doctor` printed `aef loop bless <module>`, which argparse rejects. *(docs; none)*
- **Near-miss**: the routing detector matched `Edge(to_node="reflect")` inside
  `build_graph`'s return, so it passed the exact trap it existed to catch.
  Caught only by a planted-fault test.

### ADR 0074 — the gates the CLI could not reach (8 + 2)
- **G2 and G3 had never executed from a real command.** `now_for_gates` was
  set by tests and by nothing else; G5 failed on `now=None` and the fail-fast
  pipeline stopped before the entire behavioural half. *(code; the acceptance
  test hand-built its own config — no test imported `aef.cli.loop._config`)*
- G5's refusal misnamed its own cause. *(code; none)*
- A cohort failure silently disabled three gates. *(code; none)*
- `entrypoint` defaulted to a layout nothing has, no flag to override —
  ADR 0069 defect 3 one field over. *(code; `test_cli_seams.py:102` is the
  same test for the sibling field)*
- Drift subtracted a whole-tree baseline from a changed-files-only candidate,
  rejecting the **first** candidate after a blessing. *(code; none)*
- `bless` read the working tree while every gate reads git. *(code; none)*
- The control cohort carried the candidate's own changes, so **G3 could never
  pass a multi-file candidate**. *(code; every cohort test used one file)*
- One security incident was counted twice in the digest. *(code; none)*
- **Obligation 1 had the same hole as obligation 5**: no shipped command could
  label a tripwire, and `record` could not even reach a failing case. *(code+docs; none)*

### ADR 0075 — obligation 2 broke the gates (8)
- **ADR 0073 fixed two of *three* construction sites.** The one it missed is
  the one the gates use: any adopter with a reflect node scored 0.0 for
  candidate, incumbent and all five cohort members, so **G3 rejected every
  candidate forever** while `doctor` reported the obligation green. *(code;
  this repo's demo agent has no reflect node — the one agent the gates are
  tested against was the one shape that could not expose it)*
- ADR 0074's entrypoint fix survived in G2's own default, so the driver said
  "G2/G3 will refuse" and G2 imported anyway and crashed. *(code; none)*
- The emitted CI workflows could not work in any adopting repo — three
  independently fatal reasons. *(docs; `test_workflows.py` reads aef-core's
  own workflows, not the emitted templates)*
- The weekly digest ran hourly. *(docs; none)*
- A missing `--memory` was reported as a candidate rejection. *(code; the
  existing seam test string-matches source, which cannot see `Path(None)`)*
- A grounded proposal's citations were discarded before the report. *(code; none)*
- `FileMemoryStore` silently dropped two declared fields — and had **zero tests**.
- The scaffolded agent never sets a `Plan`, making G2 vacuous. *(code; none)*

### ADR 0076/0077 — recovery, and two dead halt criteria (2 + 1 near-miss)
- A recovered run was indistinguishable from an outright failure, so graceful
  recovery was **unrewardable by the objective the loop optimises**. *(code; none)*
- Two of five halt criteria were dead parameters while the ledger held their
  evidence. *(code; tests passed the flags directly and never asserted a caller
  set them)*
- The archive's append-only property was never verified in production.
- **Near-miss**: criterion 3 first matched `"drift" in reason` — and G5's
  *other* message is "no owner-blessed baseline to measure **drift** against",
  the state every fresh adopter starts in. It would have halted the loop on the
  second run of every new repo. My own planted fault missed it because I wrote
  the fault with a paraphrase of the message.

### ADR 0078 — the fix that broke the command it audited (6)
- **ADR 0075 shipped a regression to main**: writing citations to the ledger
  passed `Citation` objects to a JSON serialiser, so `aef loop cycle` died
  outright, no gate ran, and exit 1 meant CI read it as "this candidate is no
  good". *(code; the test I wrote to defend that wire asserted
  `"proposal=proposal" in inspect.getsource(cycle)` — it checked the wire was
  connected and never sent anything down it)*
- The proposer read the working tree while the branch is built from `base_ref`,
  laundering un-proposed changes into the candidate. *(code; the fixture is
  always on `main` with a clean tree)*
- Detached HEAD — the normal CI shape — made the branch restore a no-op, so
  cycles compounded. *(code; no test uses detached HEAD)*
- A trailing comment on a constant made the proposer emit **nothing** for the
  file. *(code; tests only used bare `NAME = <number>`)*
- A five-member control cohort could be one distinct mutation, satisfying G3's
  member-counting floor with a point mass. *(code; no test asserted distinctness)*
- G0 scanned a lossily-decoded string while the runtime got bytes. *(code; all
  fixtures were valid UTF-8)*

### ADR 0079 — the half nobody swept (13)
- **Worst finding of the program: deleting a `requires_human_approval=True`
  edge scored as a maximal *improvement*.** Three gates, zero catches.
- `policy_engine` dropped at all four `Services` sites.
- Every "Start (5 steps)" command except `aef doctor` failed in a fresh adopted
  repo: wrong install line, green bar failing 4/4 (`mypy --strict aef` again),
  generated repo failing its own `ruff check .`, generated file non-conforming
  to ruff's default width, `aef` shipping no `py.typed`.
- `aef doctor` exited 1 on a pristine `aef init` repo and passed on an
  `aef_adapter.py` that was not valid Python.
- doctor's "no stated purpose" advisory could not fire on the `TODO:`
  placeholder adopt itself writes.
- Of the five per-agent config fields **only `model_provider` reaches a run**
  (ADR 0014) and no generated file said so — an adopter setting
  `require_hitl_above_risk` believed it enforced.
- *(structural: `test_adoption_sequence.py` hand-writes the two preconditions a
  real `aef adopt` output lacks, so the guard validated a hand-repaired copy of
  the thing it guards — that fixture is why five of these survived 984 tests)*

### ADR 0080 — verifying my own fixes (5)
- **A reward hack I introduced.** `RECOVERED_KEY` is written by Zone A code the
  candidate authors and *relaxes* the pass predicate: one dict key turned
  `regressed=True` into `regressed=False` on an identical broken candidate.
  `policy_denied` is safe only because Zone B alone writes it — a property I
  did not carry across.
- Three evasions of the G4 check I had written hours earlier (`git mv`,
  shadow edge, false condition), **shipped with zero tests**.
- G4 halted the loop on a benign node rename — the gate was inverted: firing
  on the safe change, silent on three hostile ones.
- Halt criterion 4's only reset was unreachable, making it a lifetime counter.

---

## 3. Rounds

**Five rounds ran. Zero were dry.** Round 5's most severe finding was
introduced by round 4's commit.

---

## 4. What an adopting repo can now do that it could not last night

Concretely, each verified by running the shipping CLI against a repo built
from the generated docs:

1. **Reach a verdict from all six gates.** Last night the pipeline stopped at
   G5 from any real command — G2 and G3 had never run outside a test. A
   coherent candidate now passes all six (`drift 0.069/0.500`, `candidate mean
   0.7143 beats cohort p95 0.4286`).
2. **Satisfy all five obligations.** Obligations 1 and 5 had no command behind
   them; obligation 2 broke obligations 1 and 3. `aef loop doctor` reports all
   five at once with runnable fixes, and a fresh repo reaches five green.
3. **Add a reflect node without disabling the gates.** That configuration
   scored 0.0 across the board last night.
4. **Record a tripwire and have it catch a reward hack.** Verified end to end:
   the hack passes G0/G1/G4/G5 (it is smaller and cheaper than the honest
   change), G2 catches it, one security event, exit 2, loop halted.
5. **Run `aef loop cycle` to completion** — harvest → propose from real memory
   → materialise → six gates, with the citations in the ledger.
6. **Run `aef adopt` → `aef doctor` and get exit 0**, with the generated repo
   passing the lint the kit prescribes; same for `aef init`.
7. **Type-check against `aef`.** It shipped no `py.typed`, so the green bar
   this project mandates for adopters was impossible for them to pass.
8. **Trust G4 to catch a removed human-approval gate**, including via `git mv`,
   a shadow edge, or a false condition — and not to halt on a rename.

---

## 5. The single decision I need from you

**How should a HITL-gated scenario be scored inside the gates?**

`scenario_runner` supplies no `hitl_approvals`, so a HITL-gated incumbent
always crashes and scores 0 — and `Comparison.regressed` short-circuits on
`not incumbent.passed`. That is why deleting a human-approval gate reads as a
maximal improvement. I fixed the *static* half (G4 now catches the removal six
ways) and deliberately did **not** fix the behavioural half, because both
options change something only you should change:

- **(a) Supply approvals in the gate.** The gate then approves things on your
  behalf so the corpus can execute. Cheap, and it makes G2/G3 see the real
  behaviour — but the harness is now auto-approving.
- **(b) Score a HITL pause as its own outcome class**, neither pass nor fail.
  Honest, and it changes what `Outcome.passed` means for every existing user —
  adjacent to the ADR 0038 line you told me not to cross.
- **(c) Leave it.** G4's static check is the sole defence. It is now tested
  against six attacks and four benign cases, but it is a mitigation, not a fix,
  and an evasion I have not thought of is not covered.

I recommend **(b)**, scoped to a new field rather than a change to
`task_completion` — same shape as the `recovered` marker, but written by the
executor (Zone B) rather than by agent code, which is precisely the property
whose absence made `recovered` hackable.

---

## Two things I want to flag about my own reliability

**I shipped a regression** (ADR 0078) and **introduced a reward hack**
(ADR 0080). Both passed a green suite of 900+ tests. Both were caught only
because a later round attacked the earlier round's work.

Twice tonight a detector passed its own planted-fault verification and was
still wrong, because I wrote the planted fault with a paraphrase of the real
value rather than the real value. That is now written down as a rule.

The honest read on this codebase: its failure mode is **seams between
individually-correct, individually-tested parts**, and a single pass over any
area — including a pass I just made — is not evidence that area is clean.
