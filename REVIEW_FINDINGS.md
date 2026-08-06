# Adversarial review — `codex/bughunt-10x` vs `main`

29 commits, 51 files, 1823 insertions, 154 deletions. Reviewed against
`REVIEW_LOOP_PROMPT.md`. Verdicts per fix: CONFIRMED / UNPROVEN / WRONG /
WEAKENS-A-CONTROL.

Method note: all probes run from a detached worktree at `/tmp/cdx`; the Codex
branch is never modified. Claims in `CODEX_BUGHUNT_REPORT.md` are treated as
claims and re-derived independently before being accepted.

---

## Lens 1 — modified EXISTING tests (highest risk: a changed test is a moved goalpost)

Four existing test files were touched. **All four checked. None weakens a
control.** Three are message-wording changes tied to a real defect; one is a
docstring correction whose substance I verified independently and found
accurate.

### 1.1 `tests/test_phase2_5_stubs.py` (+5/-2) — CONFIRMED

The assertion changed from `match="Phase 4 gate criteria"` to
`match="implemented, but have not been validated against live traffic and real
tenants"`. **The guard is unchanged**: it still requires `NotImplementedError`.
Only the expected message moved.

Verified the guard still fails closed on the branch:
```
EvolutionConfig(enabled=True): NotImplementedError -> still fails closed
  msg: evolution.enabled=True is rejected: all seven Phase 4 safety mechanisms
       are implemented, but have not been validated against live traffic and
       real tenants...
```

This is seeded calibration item #1, fixed correctly and for the right reason.
The old message was materially false — it claimed no Phase 4 criteria were
implemented, when all seven are; what they lack is live evidence. **Hard-stop
#2 honoured.**

### 1.2 `tests/config/test_schema.py` (+23/-2) — CONFIRMED

The `-2` is the same message rewording as 1.1, on the `EvolutionSettings` path.
Verified independently:
```
EvolutionSettings(enabled=True): ValidationError -> still fails closed
```
Both disablement layers intact. The remaining `+23` is three genuinely new
tests (non-UTF-8 config, and two `MemoryConfig` restrictions — see 1.5).

### 1.3 `tests/harness/test_hitl_outcome_class.py` (+1/-1) — CONFIRMED

Docstring only. `"Zone B harness code executed from the base ref"` →
`"parent harness code outside the candidate worker"`. Consequent to 1.4; the
substance is verified there. No assertion touched.

### 1.4 `tests/harness/test_trust.py` (+19/-7) — CONFIRMED, and this is the branch's most valuable finding

This is the one that looked most like a weakened control and is not.

The docstring was downgraded from an enforcement claim to a primitive claim:

> **before:** "The trust boundary — gates execute from the base ref, never the
> branch... a candidate branch rewrites the gate that judges it, and the
> rewritten gate never runs."
>
> **after:** "Acceptance tests for the explicit base-ref read primitive... a
> caller that loads a gate *through the primitive* receives the pinned base
> copy. Production execution provenance is established separately by the
> launcher/workflow."

That is a materially weaker guarantee, so I re-derived it rather than accept it.
**Codex is right.** On `main`, `BaseRefHarness` has **zero production call
sites**:

```
$ grep -rn "BaseRefHarness" aef/          # on main
aef/harness/trust.py:9:   through `BaseRefHarness`, which resolves it at ...
aef/harness/trust.py:38:  class BaseRefHarness:
```

Only its own definition. Every other reference is a test or an ADR. ADR 0047
described it as the integrated loader for every gate, corpus, suite and
evaluator byte; nothing calls it.

The second half of Codex's claim also holds — the boundary is real, it just
lives in the workflow rather than the library. `.github/workflows/loop-gate.yml`
checks out `ref: main`, `pip install -e ".[dev]"` from it, and only then fetches
the candidate into `refs/loop/candidate` as data.

**No assertion was removed.** The acceptance test still asserts a subverted gate
is rejected, and `+19` adds a strictly stronger case
(`test_the_base_sha_stays_pinned_when_the_ref_moves`) that pins the base SHA
against a ref that advances underneath it. Tests same-or-stronger; only the
prose claim narrowed, and it narrowed toward the truth.

**Operational consequence the owner should note** — this is the finding's real
value, and it bears directly on adopting AEF into another repo: the isolation
property is a property of *the supplied workflow*, not of the library. A repo
that adopts AEF and drives the loop by some other path (a local script, a
different CI system) does **not** inherit it. Codex records this as a deployment
obligation in the corrected ADR. That is the right call, but it is now a thing
the adopter must actively honour rather than something they get for free.

### 1.5 Collateral check — `MemoryConfig` restriction (new, not a modified test)

Two added tests assert `MemoryConfig(impl="mem0")` and
`MemoryConfig(impl="in_memory", backend="sqlite")` now raise. This looked like a
possible regression, since `CLAUDE.md` calls Mem0 real and tested.

It is not. `aef/config/factory.py`'s own docstring on `main` states the case:

> "`MemoryConfig` alone doesn't carry enough information to construct a real
> `mem0.Memory()` (no embedder/vector-store/LLM choice in the schema)"

There is no runtime builder for memory from config at all. A config naming
`mem0` was previously accepted and would silently run against volatile
in-memory storage — a real defect, and a dangerous one. **CONFIRMED.**

Checked it does not break adoption: the `aef adopt` template generates
`memory: impl: in_memory`, which the validator permits. Ran adopt + doctor
end-to-end against the branch on a fresh repo — clean.

Seeded calibration item #2 also confirmed fixed in the same run: `aef doctor`
now reports an unwired adapter stub as `[WARN]`, not `[OK]`.

### Lens 1 verdict

4 of 4 modified tests CONFIRMED benign. No control weakened. Both evolution
disablement layers verified intact by execution. Hard-stops #2 verified; #3 not
yet fully assessed (gates are Lens 2).

---

## Lens 2 — the two edited GATES (hard-stop #3 exposure)

**Both gates are provably behaviour-identical. Hard-stop #3 is not violated.**

`g2_outcome.py` (+3/-3) and `g4_separation.py` (+3/-2) both looked like the
highest-risk shape on the branch: a small diff inside a control. They are
docstring-only.

Not eyeballed — proven. Both versions of every changed module under `aef/` were
parsed, had all docstrings stripped from modules, classes and functions, and the
resulting ASTs compared:

```
aef/harness/gates/g2_outcome.py                         IDENTICAL
aef/harness/gates/g4_separation.py                      IDENTICAL
aef/harness/git.py                                      IDENTICAL
aef/harness/outcome.py                                  IDENTICAL
aef/services/memory/base.py                             IDENTICAL
```

Four other files that show insertions and deletions in the diffstat are likewise
pure documentation. No executable line in either gate changed, so no promotion
path became easier or harder. There is nothing here to revert-test: the core
test does not apply to a change with no behaviour.

The prose edits are consequent to the Lens 1 finding and are accurate in the
same way. G2's docstring dropped the claim that "the runner executing agent code
is the base ref's runner" in favour of naming what actually holds — state,
routing, classification and scoring stay in the parent harness, only candidate
node functions execute in the worker. G4's dropped "the gates themselves run
from the base ref regardless" for "the supplied workflow launches the gates from
trusted `main`; arbitrary local launchers must establish the same provenance."
Both narrow an overclaim toward the truth, consistent with `BaseRefHarness`
having no production call site.

**Verdict: CONFIRMED (documentation only).**

### Remaining hard-stops verified in this area

- **#6 — ADR 0038, `RuleBasedEvaluator.task_completion`.** `aef/services/eval/`
  is untouched by the branch. `aef/services/eval/rule_based.py` is byte-identical
  on both refs (3116 bytes, `ce4f53475b7a`). `aef/harness/evaluation.py` and
  `aef/config/domain_gates.py`, which consume the scalar, are also untouched.
  **CONFIRMED unchanged.**
  *(Method note: my first attempt at this compared two empty `git show` outputs
  and produced a matching hash of `da39a3ee` — the SHA-1 of the empty string. A
  match from two nothings is not a match. Redone against the real path with byte
  counts. Recorded because the same trap is what this review exists to catch.)*
- **#4 — workflow permissions and secrets.** `.github/` is untouched by the
  branch; the diff is empty. **CONFIRMED.**
- **#7 — HITL routing.** No routing change. The only `+/-` line in the whole
  `aef/` diff matching HITL/escalation is one word inside the evolution
  rejection message. `aef/harness/outcome.py` — which classifies HITL outcomes —
  is AST-identical. **CONFIRMED.**
- **#5 — nothing pushed elsewhere or to main.** `main` is at `ffdd004`; the
  Codex work exists only on `codex/bughunt-10x`, unpushed. **CONFIRMED.**

### Green bar — independently verified on the branch, not taken from the report

Run from the `/tmp/cdx` worktree with `PYTHONPATH` forced so imports resolve to
the branch copy rather than the `-e`-installed `main` (confirmed:
`TESTING: /private/tmp/cdx/aef`) — without that, the suite would have silently
tested main's code and reported green about the wrong tree.

```
1440 passed, 93 warnings in 64.16s     (main: 1398 — 42 net new tests)
mypy --strict aef : Success, 107 source files
ruff check .      : All checks passed!
ruff format       : 193 files already formatted
```

### Lens 2 verdict

Both gates CONFIRMED docstring-only by AST comparison. Hard-stops #3, #4, #5,
#6 and #7 all verified by execution or byte comparison. #2 was verified in
Lens 1. Only #1 (Tier-1 auto-merge) remains, and it is assessed in Lens 3 with
`harness/trust.py`.

---

## Lens 3 — `aef/harness/trust.py` (+43/-31), the largest churn, in the promotion path

Three behavioural changes plus a docstring correction. **Two CONFIRMED, one
UNPROVEN.** No control weakened; two of the three are genuine hardening.

### 3.1 `base_sha` pinned at construction — CONFIRMED (and a real security defect)

`BaseRefHarness.base_sha` was a property calling `self.repo.rev_parse(self.base_ref)`
on **every access**. Codex moved the resolution into `__post_init__` and froze it
into `_base_sha`.

The defect is sharper than the report states: the pre-existing docstring already
claimed the property it did not have —

> "Pinned once so a concurrent push to the base branch cannot swap the harness
> mid-run."

The docstring said pinned; the code re-resolved. A push to the base branch
during a run would silently move the trusted base underneath the harness.

Core test, both directions:
```
reverted (rev_parse on each access), new test kept:
    assert harness.base_sha == original_sha
E   AssertionError: assert 'e7eba9b452fe...' == 'c03ebdd4dc24...'
    -> the harness followed the moved ref. 1 failed.

restored: 12 passed.  worktree clean.
```
The test binds, and it fails for exactly the right reason. **CONFIRMED.**

### 3.2 `_prepare_empty_destination` — UNPROVEN

`materialize()` previously did `dest.resolve()` + `mkdir(exist_ok=True)`. It now
refuses a symlinked destination and refuses a non-empty one.

The change is defensible on its face. It has **no test anywhere**:

```
grep -rn "may not be a symlink|must be empty" tests/     -> no matches
revert the hardening, run the FULL suite               -> 1440 passed
```

Reverting it breaks nothing. By the brief's own standard — every fix carrying a
test that fails without it — this one does not qualify. **UNPROVEN.**

Two mitigating facts, stated so the verdict is not overread. The analogous
hardening in `workspace.py` *is* tested, by three cases in
`tests/harness/test_gates.py` (non-empty destination, symlink destination,
executable bits preserved); Codex tested the workspace path and not the
`BaseRefHarness` one. And `materialize()` has no production caller, since
`BaseRefHarness` has none at all (Lens 1) — so the practical exposure is nil.
It is an untested behaviour change in dead code, not a live risk.

### 3.3 `verify_base_is_ancestor` docstring — CONFIRMED

Changed from "Assert the candidate actually descends from the base ref" to
"Assert the candidate and base share history... despite this method's historical
name, the base need not be an ancestor."

Checked against `main`'s implementation rather than taken on trust: the method
only calls `repo.merge_base(...)` and raises when it errors or returns empty. It
never invokes `git merge-base --is-ancestor`. **The method never asserted
ancestry.** The name and old docstring overclaimed; the correction is accurate
and the behaviour is unchanged.

### Systematic bound-test sweep (whole branch, not just this lens)

Rather than revert-test twenty fixes one at a time, `aef/` was reverted to
`main` wholesale with all branch tests retained. Every test that then fails is
bound to some fix:

```
unique bound tests: 36, across 19 test files
  5 tests/services/memory/test_in_memory.py     2 tests/security/test_tool.py
  4 tests/config/test_schema.py                 2 tests/observability/test_in_memory.py
  4 tests/cli/test_doctor.py                    2 tests/kernel/test_durability.py
  3 tests/harness/test_gates.py                 2 tests/harness/test_isolated_evaluation.py
  2 tests/cli/test_adopt.py                     1 each: test_phase2_5_stubs, test_schema(state),
                                                  test_runtime, test_memory_retriever,
                                                  test_mem0_adapter, test_base(providers),
                                                  test_anthropic_provider, test_trust,
                                                  test_candidate, test_run
```

Every changed subsystem is represented. The branch adds 42 net new tests and 36
of them bind, which is a good ratio — the fixes are, in the main, genuinely
tested rather than asserted.

*(Method note: the first attempt at this sweep used `git checkout main -- aef/`,
which STAGES the revert; `git checkout -- aef/` then appeared to restore while
leaving the files staged. Restored properly with `git reset HEAD -- aef/`
followed by checkout, and confirmed `0 modified` against branch HEAD `dd0bb8d`.
The Codex branch itself was never modified.)*

### Hard-stop #1 — Tier-1 auto-merge — CONFIRMED not enabled

The last unassessed hard-stop. Across the entire `aef/` diff, the only lines
matching tier / auto-merge / promote / promotion are two added *references* to
`docs/trust/promotion-trust-case.md` inside the evolution rejection messages —
pointing the reader at the document that argues against auto-merge. No promotion
authority module exists to be touched, and `docs/trust/` is untouched by the
branch.

**All seven hard-stops now verified.**

### Lens 3 verdict

2 CONFIRMED, 1 UNPROVEN (untested hardening in code with no production caller),
1 docstring correction verified accurate against the implementation. Nothing
loosened what may be promoted or who must approve it.

---

## Lens 4 — the ADR 0047 rewrite (66 lines) and `docs/roadmap.md` (+9)

Lens 1 settled that the *substance* of the correction is accurate. This lens
asks whether the rewritten record over- or under-states it, and whether editing
an ADR in place was the right move.

**Verdict: content CONFIRMED accurate. One process departure worth raising, and
two falsifiable claims lost.**

### 4.1 The correction is marked, not laundered — CONFIRMED

My main concern going in was that history had been rewritten so a reader could
no longer see what was previously believed. It has not. The rewrite opens with a
dated block that quotes the original claim and states plainly that it was wrong:

> **Implementation correction (2026-08-06):** the original decision text said
> every gate, corpus, suite, and workflow byte was loaded through
> `BaseRefHarness`. That is not the integrated call path... The decision and
> confidence below are narrowed accordingly.

That is the honest form. A reader of the ADR alone learns both the original
belief and the correction.

### 4.2 It neither under- nor over-states — CONFIRMED

**Not under-stated:** it does not read as "there is no boundary." It still
asserts one exists and names it — "In the supplied CI workflows, AEF is checked
out and installed from `main`; only after that is the candidate fetched under a
data ref... This is the integrated boundary." Verified against `loop-gate.yml`
in Lens 1.

**Not over-stated:** it states the limit precisely rather than glossing it —
"it cannot repair an untrusted launcher that imports AEF from the candidate
checkout," and a new Consequences bullet, "the package cannot attest its own
import provenance."

### 4.3 The Confidence upgrade is legitimate — CONFIRMED

The rewrite replaces the original's

> "Notably unexamined: `.gitattributes` filters, and whether a candidate can
> influence git config in a way that changes diff output."

with a claim that real-repository tests now cover attributes, unusual config,
symlinks, submodules, modes, ignored files and workspace overlays. A confidence
*upgrade* is exactly the shape of an over-statement, so it was checked rather
than accepted.

It holds — and for a reason the report does not mention: **those tests already
existed on `main`.** `tests/harness/test_gates.py` carries three
`.gitattributes` cases on both refs, including the binary-marking numstat escape
and the `export-ignore` workspace case (the work recorded in ADR 0062).
`test_policy_config_path.py` carries 40 git-config references on `main`. The
original "notably unexamined" line was **already stale before this branch
touched it**. Codex corrected a claim that had aged out, not inflated a new one.

### 4.4 Two falsifiable claims were deleted — minor loss

The Consequences section lost:

> "97 tests, every git behaviour exercised against a real `git init` repo. The
> three escapes each have a known-bad test that fails if the control is removed."

replaced by the vaguer "Real-Git tests cover the explicit read and candidate
reconstruction primitives."

The `97` was stale by roughly 9× — `tests/harness/` now collects **854** tests —
so deleting a specific number that wrong is defensible. But "each escape has a
known-bad test that fails if the control is removed" is a *binding* claim, the
same property this review has been testing for all along, and its replacement
asserts nothing checkable. Recommend restoring a binding claim with a current
number rather than leaving prose.

### 4.5 Process departure — this should probably have been a new ADR

**The repo has an established supersession convention, and this edit departs
from it.** ADR 0044 "supersedes 0041, whose palette premise was disproved."
ADR 0094 "Supersedes the security model of ADR 0085 and 0088, both defeated."
Five ADRs carry supersession markers.

The direct precedent is **ADR 0063**, described in the index as "Phase 1c
doc-vs-code audit: 18 of 19 checked claims accurate, one false." When an audit
previously found a false claim in an ADR, this repo recorded the finding as a
**new ADR** rather than editing the old one.

There is a real argument for the in-place edit — a reader who opens 0047 alone
sees the correction immediately, whereas a superseding ADR risks 0047 being read
and believed on its own. And a superseding ADR is normally for a changed
*decision*, whereas here the decision arguably stands and only its description
of the implementation was wrong. Codex's dated correction block mitigates most
of the risk.

But an ADR edited to match the code reverses the direction of authority, which
is precisely what the convention exists to prevent, and the owner is the one who
should decide whether this case is an exception. **Flagged for the owner, not
fixed.** Not a merge blocker: no information is lost or hidden.

### 4.6 `docs/roadmap.md` (+9) — CONFIRMED accurate

Phase 4 previously read "Every method raises `NotImplementedError`;
`EvolutionConfig(enabled=True)` itself raises, naming every unmet gate
criterion" and "Re-enabling requires implementing ALL of:". Since all seven
mechanisms are in fact built, both were false. The new text — the guard
"explains that live-traffic and real-tenant validation is still missing", and
"Re-enabling requires **owner acceptance** of ALL of:" — matches the list below
it, where every entry is already marked **BUILT**, and matches the two guards
verified fail-closed in Lens 1. The section still reads **STUBBED, DISABLED**.

### Lens 4 verdict

4 CONFIRMED (correction marked; neither over- nor under-stated; confidence
upgrade legitimate; roadmap accurate). 1 minor loss (deleted binding claim about
known-bad tests). 1 process departure flagged for the owner (in-place ADR edit
where the repo's convention, and ADR 0063's precedent, is a new superseding
record).

---

## Lens 5 — the remaining subsystem fixes

Judged on quality — cause vs symptom, and whether the fix opened an uncovered
path. The bound-test sweep (Lens 3) already established each has a binding test,
so it was not re-run. The core test was applied to the three
highest-consequence fixes.

**Verdict: CONFIRMED across the board, and the quality is good. One instance of
the same bug class was MISSED — reproduced below.**

### 5.1 `kernel/durability.py` — CONFIRMED, and it is a seam defect

The best fix on the branch after the `base_sha` pin. `_run_dir()` on `main`
already resolved and validated the path — but only the WRITE path used it.
`load_checkpoint`, `list_checkpoints` and `load_cursor` each built
`self._root / run_id` **directly**, bypassing the check entirely. The guard
existed and three readers walked around it.

That is the seam shape this repo's own ADR 0063 describes: two correct
components, a defect in the join. Codex routed all three readers through
`_run_dir(run_id, create=False)` — the `create` flag being necessary so a read
does not materialise a directory as a side effect, which is the right call
rather than the easy one.

Also fixed: `load_cursor` accepted valid JSON of the wrong shape.
`{"next_node": 7}`, `{}`, `[]` and `"node_b"` all previously coerced to `None`
via `data.get(...)` plus an `isinstance` fallthrough — i.e. a corrupt cursor read
as "no cursor", silently restarting a run from the beginning. Now raises
`CorruptedCheckpointError`.

Core test:
```
reverted -> FAILED test_file_backend_reads_reject_run_ids_that_escape_the_root[load_checkpoint]
            FAILED ...[list_checkpoints]
            FAILED ...[load_cursor]
            FAILED test_load_cursor_rejects_valid_json_with_invalid_schema[{"next_node": 7}]
            FAILED ...[{}]  FAILED ...[[]]
restored -> passes
```
Six parametrised cases bind. **CONFIRMED.**

### 5.2 `providers/base.py` — CONFIRMED

One line: `self._providers = tuple(providers)`. The caller's list was aliased, so
mutating it after construction silently changed the fallback order — or emptied
it. Core test reverted:
```
E  aef.providers.base.ModelProviderError: all providers failed:
```
with an **empty** summary — the provider iterated over nothing, which is exactly
the cleared-list symptom. The test constructs, then calls `providers.clear()`,
then asserts. **CONFIRMED.**

### 5.3 `security/tool.py` — CONFIRMED (two fixes)

`InMemoryAuditLogWriter.write` now stores `deepcopy(entry)`. `AuditEntry` is a
frozen dataclass, which freezes the *binding*, not the nested `arguments` dict —
so a caller could rewrite the recorded arguments **after** policy evaluation.
For an audit log that is the whole point of the artefact. The test passes a
nested dict, evaluates, mutates `arguments["nested"]["value"]`, and asserts the
stored entry still reads `at-evaluation` — so it requires a DEEP copy, not a
shallow one.

Second: `config or PolicyConfig()` → `config if config is not None else ...`,
and likewise for `audit_log` and `clock`. A caller-supplied `AuditLogWriter`
defining `__len__`/`__bool__` falsey was silently discarded and replaced with an
in-memory sink — security audit records written to a throwaway list instead of
the caller's writer. Narrow, but the consequence is losing the audit trail.

Both bind: reverted, `test_in_memory_audit_entry_is_a_snapshot_of_nested_call_arguments`
and `test_explicit_falsey_audit_log_dependency_is_honored` fail. **CONFIRMED.**

### 5.4 `services/memory/in_memory.py` (+35/-16) — CONFIRMED

Four distinct issues, each addressed at the cause:
- `clock if clock is not None` — same falsey-dependency class.
- `RLock` around read and write.
- `deepcopy(record.content)` on write **and** `_snapshot(record)` on query
  return, so neither the caller nor the store can mutate the other's copy. Both
  directions, which is the part usually missed.
- `limit < 0` now raises. Previously `matches[:limit]` with `limit=-3` silently
  returned all but the last three records — a wrong answer, not an error.

### 5.5 The rest — CONFIRMED by binding tests, spot-checked for quality

`state/schema.py`, `config/loader.py`, `cli/{adopt,doctor,run}.py`,
`services/memory/adapters/mem0_adapter.py`, `services/context/memory_retriever.py`,
`providers/anthropic_provider.py`, `observability/in_memory.py`,
`services/runtime.py`, `harness/{candidate,isolated,isolated_suite,workspace}.py`.
Each carries at least one test that fails when `aef/` is reverted (Lens 3
sweep). The recurring shapes are the two above — defensive snapshot of
caller-owned mutable state, and `is None` instead of truthiness — applied
consistently.

### 5.6 WHAT CODEX MISSED — one instance of its own bug class, reproduced

Codex fixed the falsey-dependency bug in `security/tool.py` (×3),
`providers/anthropic_provider.py`, and `services/memory/in_memory.py`. A sweep
for the remaining pattern across `aef/` returns exactly one survivor:

```
aef/observability/otel_tracer.py:54
    self._tracer = otel_tracer or get_tracer(instrumentation_name)
```

`aef/observability/` **was** touched by this branch (`in_memory.py`), so the
subsystem was in scope. Reproduced rather than argued:

```
caller passed : FalseyTracer
actually used : ProxyTracer
HONORED       : False
```

An explicitly injected tracer is silently discarded in favour of the global one.
Consequence is lower than the audit-log case — spans go to the default tracer
rather than nowhere — and it needs a tracer object defining `__bool__`/`__len__`
falsey, which the standard OTel types do not. So: **real, same class, lower
severity, and inconsistent with the five siblings that were fixed.** Recommend
fixing for consistency; not a merge blocker.

### Lens 5 verdict

All reviewed fixes CONFIRMED. Three core-tested in both directions with failure
text read and matched to the defect. Quality is good — these address causes, and
the snapshot fixes guard both directions rather than only the obvious one. One
missed instance of Codex's own bug class, reproduced.

---

## Lens 6 — report-vs-diff honesty

**Verdict: the report is honest. The headline suspicion — ten rounds with no dry
round — does not survive contact with the evidence, and the report is more
conservative than the branch it describes.**

### 6.1 Count matches the diff — CONFIRMED

21 `fix(` commits, 10 round-record `docs:` commits, 29 total. The report
declares exactly 10 rounds and 14 numbered findings in its summary, with the
remainder folded into multi-defect rounds. Nothing in the report lacks a commit;
nothing in the diff lacks a report entry.

Self-reported per-round gate counts are monotonic and terminate at the real
number:
```
1398 -> 1404 -> 1411 -> 1416 -> 1426 -> 1428 -> 1440
```
`1398` is exactly `main`'s count and `1440` is exactly the branch's, both
independently measured in Lens 2. The report's arithmetic is checkable and
checks out.

### 6.2 Reproductions are present, including where I first thought they were not

My initial pass flagged Round 4 — the concurrency round, whose fixes are the
`deepcopy`/`tuple`/`RLock` hardening most likely to be defensive padding — as
having **zero** reproduction blocks. That was **my instrument, not the report**:
I grepped case-sensitively for `Reproduction`, and Round 4 writes *"Direct
reproduction before the fixes:"*. Recounted case-insensitively, all ten rounds
carry reproduction language and a transcript block.

Round 4's transcripts are concrete and, in one case, identical to what I derived
independently in Lens 5 without having read them:
```
fallback_after_caller_list_clear= ModelProviderError 'all providers failed: '
```
That is the same empty-summary symptom my own revert produced. Also
`RuntimeError: dictionary changed size during iteration` from a two-thread
probe, which is a genuine live trigger rather than a theoretical one.

*(Recorded because it is the fourth method trap of this review, and the same
class as the others: a null result from an instrument I had not proved bites.)*

### 6.3 No dry round is NOT padding here — CONFIRMED

The brief permitted dry rounds and warned against manufacturing findings, so
10-for-10 was the right thing to be suspicious of. It holds up, for reasons
independent of the report's own testimony:

- Each round is a **different subsystem lens** (replay, policy, providers,
  concurrency, config, boundary values, resource lifecycle, CLI, harness
  isolation, docs). These are not ten passes over the same ground.
- I independently confirmed the substance of the largest findings — the
  durability read/write seam, the `base_sha` pin, fallback aliasing, audit
  deep-copy — by reverting and watching them fail for the right reason.
- 36 of 42 new tests bind (Lens 3 sweep).

The honest qualifier: a number of these are **latent** defects — real breaches
of a documented contract that no current production path triggers, because
nothing today passes a falsey dependency or mutates a caller-owned dict after
the call. The report does not oversell this; Round 4 justifies each against the
specific documented claim it contradicts ("audit/telemetry are historical
records"), which is the correct standard.

### 6.4 The report is more conservative than the branch — CONFIRMED

This is the strongest evidence against padding, and it runs the opposite way:

- **Section B, "Suspected but unconfirmed"** — five items explicitly NOT fixed
  because they could not be reproduced, including `_atomic_write_text` leaving a
  temp file and `Services.tools` retaining caller-owned mappings. A padding
  report converts these into fixes; this one declines.
- **12 "deferred / suspected / not classified" mentions** across the rounds.
- **Section D, "What I would not run unattended"** — states Tier-1 and evolution
  should stay off pending live-traffic evidence, matching
  `docs/trust/promotion-trust-case.md` rather than arguing its own work has
  earned more trust.

### 6.5 One CONFIRMED defect it found and deliberately did NOT fix — verified

The most consequential item on the branch is a fix that is not on it.

`hitl_approval_key(from_node, to_node)` returns `f"{from_node}->{to_node}"`. The
delimiter is not escaped, so distinct edges collide. Reproduced independently on
`main`, without reference to the report's transcript:

```
hitl_approval_key('a->b','c') = 'a->b->c'
hitl_approval_key('a','b->c') = 'a->b->c'
COLLIDE: True
```

An approval minted for edge `("a->b", "c")` therefore satisfies the gate on the
different edge `("a", "b->c")`. That is a **safety-relevant authorization
collision** and it contradicts ADR 0011's claim that approvals are edge-specific
and explicit.

Codex found it, reproduced it, and **did not fix it** — citing hard-stop #7, "no
routing altered into a HITL-gated edge" — and escalated it to the owner with a
recommendation to choose a collision-free approval identity and a migration
policy. It also lists it in Section C as "the one confirmed open contradiction."

**That is the correct call, and it is the single best signal in this review.**
An agent optimising for a good-looking report fixes it and claims another
finding. This one hit a constraint, stopped, and told the owner. Combined with
the AST-verified fact that no gate behaviour changed (Lens 2), the constraints
were honoured rather than routed around.

**Owner action required** — this is a live defect on `main` today, independent of
whether this branch merges. Severity depends on whether node identifiers can
contain `->`. If node ids are caller- or agent-controlled (and with self-coding
they are), the collision is reachable.

### Lens 6 verdict

CONFIRMED honest. Count matches, gate numbers verifiable, reproductions present
in every round, and the report withholds more than it claims. One confirmed
unfixed defect, correctly escalated rather than silently patched.

---

## Lens 7 — what Codex missed (my own hunt)

Time-boxed, reusing this review's own techniques rather than starting a fresh
program. Three targets: the proven unescaped-delimiter class, the
guard-bypassed-by-a-sibling-path class, and the report's own Section B.

### 7.1 `otel_tracer.py` — CONFIRMED MISS (carried from Lens 5)

```
aef/observability/otel_tracer.py:54
    self._tracer = otel_tracer or get_tracer(instrumentation_name)
```
Reproduced: a caller-supplied falsey tracer is silently replaced by the global
`ProxyTracer`. Codex fixed this exact pattern in five other places and this
subsystem was in scope (it edited `observability/in_memory.py`). Latent — needs
a tracer defining `__bool__`/`__len__` falsey, which the standard OTel types do
not — but inconsistent with its siblings. **Recommend fixing for consistency.**

### 7.2 A second delimiter collision — SUSPECTED, then RULED OUT by reproduction

`hitl_approval_key`'s collision (Lens 6) is a proven class, so I swept for
others. `aef/harness/transformations.py:126` looked like a match, and a worse
one, because it is a *safety* check:

```python
where = f"{_rendered(kwargs.get('from_node'))}->{_rendered(kwargs.get('to_node'))}"
out.append((f"{kind}:{where}", field, ast.unparse(kwargs[field])))
```

`_assert_controls_untouched` compares these signatures to detect an owner-only
field (`requires_human_approval`, `fallback_node_id`, …) **moving between
edges** — the exact scenario ADR 0089 records as a real past defect. My
hypothesis: `Edge("a->b","c")` and `Edge("a","b->c")` collide, so moving the
flag between them would be invisible.

Built the case and ran it. **The hypothesis is wrong:**
```
signature BEFORE: [("Edge:'a->b'->'c'", 'requires_human_approval', 'True')]
signature AFTER : [("Edge:'a'->'b->c'", 'requires_human_approval', 'True')]
signatures equal: False
RESULT: fired -> TransformationError: transformation altered an owner-only
        safety declaration
```

`_rendered()` emits the node ids **with quotes**, and the quoting acts as an
escape — `'a->b'->'c'` and `'a'->'b->c'` are distinct. The check fires
correctly. **Not a finding.** Recorded because it is the difference between this
and `hitl_approval_key`, which has no such quoting, and because a plausible
argument was wrong in a way only running it revealed.

### 7.3 `Services.tools` aliasing — CONFIRMED present, and Codex's deferral was RIGHT

The report's Section B lists this as suspected-but-not-classified. It is real:
```
Services.tools aliases the caller dict: True
  -> caller can add a tool after construction: ['a', 'b']
```
`Services` is frozen and the field is typed `Mapping[str, Tool]` — a read-only
protocol holding a mutable dict. Same "frozen outer, mutable inner" shape as the
audit-entry defect Codex *did* fix.

Its stated reason for not fixing it was that no executing core path resolves
tools from `Services.tools`. **Verified:** the only reference in `aef/` is
`shadow.py:201` passing it through; the two `config.tools` hits are
`AgentConfig.tools`, the allow-list, which is a different object. So it is
latent, and classifying it as suspected rather than fixing it was correct
judgment, not an omission.

### 7.4 mindgraph verification — CONFIRMED, after a false alarm of my own

Required by the brief and not previously run against the branch. First run:

```
VERIFY: FAIL (14 of 142)
```

142 checks, not 287. Cause: `dist/` is gitignored, so a fresh worktree has no
artifact and most checks bail early. Built it, then:

```
built
VERIFY: PASS (287 checks)
SELF-TEST: PASS (29 detections, no false positives)
```

Codex's claim of 287/29 is accurate. **Not a branch regression** — but worth
knowing that mindgraph's verifier needs a build first in a fresh clone, which is
a footgun for anyone adopting this repo.

### Lens 7 verdict

One confirmed miss (`otel_tracer.py`), one suspected collision ruled out by
reproduction, one Section B item confirmed present with Codex's deferral
judgment verified correct, and mindgraph confirmed green at 287/29.

---

# RECOMMENDATION: MERGE WITH CHANGES

The changes are small and **none of them blocks the merge**. This branch fixes
real defects, weakens nothing, and its report is honest.

## Verdict tally — 21 fix commits

| verdict | count |
|---|---|
| CONFIRMED | 20 |
| UNPROVEN | 1 |
| WRONG | 0 |
| **WEAKENS-A-CONTROL** | **0** |

## Why merge

- **All seven hard-stops verified by execution or byte comparison**, not by
  reading the report. Both evolution guards fail closed; `.github/` untouched;
  `aef/services/eval/` byte-identical (ADR 0038 intact); both edited gates
  AST-identical after docstring stripping; no promotion authority touched.
- **The green bar is real.** Independently reproduced on the branch with
  imports forced to the branch tree: 1440 passed (main 1398), mypy strict clean
  over 107 files, ruff clean, 193 files formatted, mindgraph 287 + 29.
- **The defects are real.** Five core-tested in both directions, each failing
  for the right reason with the error text read. The whole-package revert sweep
  binds 36 of 42 new tests.
- **Two findings are genuinely valuable**: the `base_sha` pin (the docstring
  claimed a property the code did not have — the trusted base could be swapped
  mid-run) and the durability read/write seam (a guard existed and three readers
  walked around it).
- **The report withholds more than it claims** — five suspected items left
  unfixed, and it recommends against unattended Tier-1.

## Residual risk — stated plainly

**I am confident in 20 of 21 fixes.** Five were core-tested in both directions
individually; the rest rest on the whole-package revert sweep plus code reading,
which is weaker evidence than an individual revert probe. I did not
independently re-derive every claimed defect on `main` — for the CLI, config,
state and harness-worker fixes I confirmed a binding test exists and the fix
addresses a cause, but did not reproduce the original failure myself.

Four of my own method errors were caught and corrected mid-review (empty
`git show` outputs hashing equal; a staged revert masquerading as a restore;
a case-sensitive grep producing a false "no reproduction" finding; a plausible
collision hypothesis that reproduction disproved). Each was found because
something was run rather than argued. **The rate at which my own probes were
wrong is the best available estimate of the rate at which the un-probed
conclusions may also be wrong.**

## OWNER ACTION

1. **`hitl_approval_key` collision — live on `main` today, independent of this
   merge.** `f"{from_node}->{to_node}"` is unescaped, so
   `hitl_approval_key('a->b','c') == hitl_approval_key('a','b->c')`. An approval
   minted for one edge satisfies the gate on a different edge, contradicting
   ADR 0011. Codex found it, reproduced it, and correctly refused to fix it
   under hard-stop #7. **Reachable if node ids are agent-controlled — and with
   self-coding they are.** Needs a collision-free approval identity and a
   migration policy. This is the highest-priority item in this review.
2. **`aef/observability/otel_tracer.py:54`** — fix the surviving truthiness
   instance for consistency with the five that were fixed.
3. **`trust.py::_prepare_empty_destination`** — either add the two tests
   (symlink destination, non-empty destination) that `workspace.py` already has,
   or drop the change. Untested behaviour change; exposure is nil today because
   `materialize()` has no production caller.
4. **ADR 0047 convention** — the correction was made in place with a dated block
   quoting the original. The repo's convention is a new superseding ADR
   (0044→0041, 0094→0085/0088), and ADR 0063 is the direct precedent for
   recording a doc-vs-code false claim as its own ADR. Your call whether this
   case is an exception. Nothing is hidden either way.
5. **Restore a falsifiable claim to ADR 0047's Consequences** — the rewrite
   dropped "the three escapes each have a known-bad test that fails if the
   control is removed" in favour of unfalsifiable prose. The `97 tests` figure
   beside it was stale by ~9× (now 854), so dropping *that* was right.

## One thing worth saying about the exercise

The strongest signal in this review is not any fix. It is that Codex found a
safety-relevant authorization defect, reproduced it, and **stopped** — because
fixing it would have crossed a hard stop — then escalated it to the owner. An
agent optimising for a good-looking report fixes it and books another finding.
Combined with the AST-verified fact that no gate behaviour changed anywhere on
the branch, the constraints were honoured rather than routed around.
