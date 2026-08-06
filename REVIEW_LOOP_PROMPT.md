# Loop prompt — adversarial review of the Codex bug-hunt branch

Paste the block below after `/loop`.

---

LOOP_PROMPT — adversarial review of `codex/bughunt-10x` against `main`.

You are reviewing work you did not do, submitted with a report that claims it is
correct. **The report is a claim, not evidence.** Your job is to find where it is
wrong, not to confirm it is right.

Repo: `/Users/raptor/aef-core`. venv at `.venv`. Branch `codex/bughunt-10x`,
29 commits, 51 files, **1823 insertions and 154 deletions**. Report at
`CODEX_BUGHUNT_REPORT.md`. Do not merge, do not push to main, do not modify the
Codex branch — write findings only.

## The prior that should govern this review

Every adversarial round in this program's history has found a defect — six for
six — in freshly written code believed correct. A 20-fix branch produced in one
autonomous pass, self-reported as green, is not the first thing that should
break that streak. If you finish a lens with nothing, that is a real result, but
reach it by looking, not by reading the report and agreeing.

The single highest-value question is not "is each fix correct?" It is **"did any
fix weaken a control to make something pass?"** — because that inverts the value
of the entire exercise and it is what a self-graded run is structurally most
likely to do.

## Highest-risk surface, ranked. Start here, not at commit 1.

1. **Modified EXISTING tests** — an added test is a claim; a changed test is a
   moved goalpost. Four were touched:
   `tests/config/test_schema.py` (+23/-2), `tests/harness/test_trust.py`
   (+19/-7), `tests/test_phase2_5_stubs.py` (+5/-2),
   `tests/harness/test_hitl_outcome_class.py` (+1/-1).
   For each deleted or altered assertion: what did it used to enforce, does
   anything still enforce it, and would the old assertion fail on the new code?
2. **Gates were edited.** `aef/harness/gates/g2_outcome.py` (+3/-3) and
   `g4_separation.py` (+3/-2). Constraint #3 forbids weakening a gate to make
   something pass. Three-line diffs in a gate deserve more scrutiny than
   three-hundred-line diffs elsewhere.
3. **`aef/harness/trust.py` (+43/-31)** — the largest churn on the branch, in
   the promotion-trust path. Verify nothing here loosens what may be promoted or
   who must approve it.
4. **An ADR was rewritten.** `docs/adr/0047-the-trust-boundary-is-the-base-ref.md`
   (66 lines changed). ADRs record decisions. Editing one to match new code
   reverses the direction of authority. Did the decision change, or did the
   record get adjusted to fit?
5. **`docs/roadmap.md` (+9)** — the authoritative real-vs-stubbed answer.
   Confirm it still describes what exists.

## THE CORE TEST — apply to every fix

A fix is unverified until its test is shown to BIND:

```
revert ONLY the source change (keep the new test) -> the test MUST fail
restore the source change                          -> the test MUST pass
```

Use a scratch worktree or `git stash`; never modify the Codex branch. If the new
test passes without the fix, the fix is unproven and the finding is dead —
record it, regardless of what the report says. This is the check that catches a
plausible fix for a defect that never existed.

Reproduce first, always: construct the case and RUN it. An exit code alone is
not evidence — read the error text and confirm it names what you think it names.
Clear `__pycache__` before any revert probe; stale bytecode has produced a false
green in this repo already.

## Hard stops — verify Codex honoured all seven, do not violate them yourself

1. Tier-1 auto-merge not enabled, on any evidence.
2. `aef/evolution/` still disabled; **both** layers intact
   (`EvolutionConfig(enabled=True)` and `AgentConfig`'s `evolution.enabled`).
   Note `aef/evolution/engine.py` was edited (+10/-8) — check it directly.
3. No gate, zone rule or budget weakened.
4. No secret or write permission added to any workflow — diff
   `.github/workflows/` explicitly.
5. Nothing pushed to another repo, nothing on main.
6. `RuleBasedEvaluator.task_completion` semantics unchanged (ADR 0038).
7. No routing altered into a HITL-gated edge.

Treat these as claims to verify, not as rules you assume were followed.

## Each iteration: ONE lens, then stop

1. **Orient.** `git diff main...codex/bughunt-10x` for the slice under review.
   Read the report's section for it — then set the report aside and read the
   code. Form your own view before absorbing theirs.
2. **Pick the earliest unreviewed lens** from the ranked list above, then the
   remaining fixes grouped by subsystem (kernel/state, harness, cli, memory,
   providers, security, observability, config).
3. **Attack it.** For each fix in the lens: does the defect it claims actually
   exist on `main`? Reproduce it there. Does the fix address the cause or the
   symptom? Does the new test bind (the core test above)? Did the fix introduce
   a new path — error handling, resource lifecycle, concurrency, boundary
   values — that nothing covers?
4. **Verify on the real green bar**, not the report's word:
   `pytest -q ; mypy --strict aef ; ruff check . ; ruff format --check aef tests examples`
   and `cd mindgraph && python tools/verify && python tools/verify --self-test`
   (287 checks, 29 detections).
5. **Record** in `REVIEW_FINDINGS.md` — append only, one section per lens:
   what you checked, what binds, what does not, what you could not reproduce,
   and a verdict per fix of CONFIRMED / UNPROVEN / WRONG / WEAKENS-A-CONTROL.
6. Report in ≤10 lines: LENS, CHECKED, CONFIRMED, PROBLEMS, NEXT. Then stop.
   Never start the next lens in the same run.

## Also answer, once the fixes are reviewed

- **Does the report's count match the diff?** Twenty-odd fixes across ten
  rounds, with no dry round, is a suspicious distribution given the brief
  explicitly permitted dry rounds. Are any "fixes" style changes or defensive
  additions with no underlying defect?
- **What did it miss?** Run your own short hunt on the seams the report does not
  mention. A reviewer who only checks the answers given cannot find the ones
  omitted.
- **Are the two seeded calibration items fixed correctly** — the
  `evolution.enabled` message (all seven Phase 4 criteria ARE implemented; what
  they lack is live evidence) and `aef doctor` reporting an unwired adapter stub
  as `[OK]`?

## Done

Every commit reviewed, every fix given a verdict, all seven hard stops verified,
green bar independently confirmed on both suites, `REVIEW_FINDINGS.md` complete
with a merge recommendation: **merge / merge-with-changes / do-not-merge**, and
the reasoning stated as findings rather than impressions.

State the residual risk plainly. If you reviewed 20 fixes and are confident in
17, say 17 — a review that reports uniform confidence has not been adversarial.
