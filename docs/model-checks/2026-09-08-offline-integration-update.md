# Offline integration update — 2026-09-08

The five source changes approved after the parcel-repo trial are implemented
and verified locally. They remove integration workarounds and improve failure
detection. They do not establish a learning gain; the earlier negative result
remains unresolved.

Work continued on `codex/model-review-20260908`, based on
`6786c4a1d922f15ff1f1a398191ab9170838f51f`, preserving the existing uncommitted
review and target-command work. Nothing was committed, pushed or deployed.
This update did not run integration against or edit the actual parcel target:
`/Users/raptor/Documents/Codex/2026-09-08/we-are-looking-at-out-parcels`.
Its existing pinned AEF wheel has not been refreshed.

## Changes and evidence

| Approved change | Result | Regression evidence |
|---|---|---|
| Exact graph budgets | END consumes no node budget. Exactly N executed nodes can finish with `max_steps=N`; an unfinished graph cannot execute node N+1. | Completion, terminal cursor, interrupted execution and one-node resume; restoring either boundary defect fails. |
| Explicit offline runtime | Required `model_provider` accepts explicit `null`. Construction and doctor support it; LLM reflection and live model gates reject it. | Provider-construction tripwire; invalid-setting tests; actual installed CLI runs with no model calls. |
| Offline adoption and opt-in workflows | Target launcher defaults to offline onboarding. Direct `aef adopt` retains the model profile for compatibility. Both require `--with-workflows` to generate workflows; offline plus workflows is invalid. | Defaults, explicit opt-in, invalid combinations before writes, and preservation of existing config/guides/workflows. |
| Source-preservation checks | Launcher compares source manifests before and after its child, including ignored entries, permissions, mtimes, hashes, symlinks and external Git metadata. Drift or an unverifiable snapshot returns nonzero. | Deliberate content, mode, timestamp, addition, deletion, ignored-file and Git changes with child exits 0 and 7; external metadata coverage and nonregular-file refusal. |
| Installed-package integration regression | A wheel built from a disposable source copy is installed into an isolated package directory and exercised in a fresh adopter. | Offline adoption, preserved owner instructions, Claude/Codex/Grok entry files, CLI doctor/run/eval/trace, persisted outcomes and provenance, policy denial/HITL tripwires, checkpoint/resume and deterministic replay. |

The installed-package test supplies the domain graph itself: calculate,
validate, reflect, END. It runs one success and one failure, verifies both
recorded outcomes, and confirms replay does not append memory again. A changed
deterministic calculation is rejected during replay. Adoption still writes a
stub; it does not infer or implement domain semantics.

`hatchling` was already the package's build backend. It is now in the dev extra
so the wheel regression has its build prerequisite. No runtime dependency was
added. The wheel test reuses the test interpreter's dependencies; it is not a
fresh dependency-resolution or supported-Python-version matrix.

## Validation

All final commands below exited 0 on Python 3.13. The complete outputs are in
[validation evidence](evidence/2026-09-08-offline-integration-validation.txt).

| Check | Observed result |
|---|---|
| Full pytest suite, activated `.venv` | 3,237 passed, 8 skipped, 1 xfailed; 216 warnings; 175.82 seconds |
| Focused profile, installed-wheel and launcher tests | 35 passed |
| `mypy --strict aef examples` | 139 source files clean |
| `ruff check .` | Passed |
| `ruff format --check aef tests examples` | 329 files already formatted |
| `make measure-ci` with `.venv/bin/python -B` | 75 rows reproduced; 1 expected drift; 0 unexplained; drift set unchanged |
| Disposable mutation checks | Unmodified baseline passed; all 8 mutations detected by assertion failures |

The [mutation evidence](evidence/2026-09-08-offline-integration-mutations.json)
records exact replacements, source and mutated hashes, commands and failure
output. Cases restore the END boundary bug, allow a budget overrun, remove
offline schema support, bypass the LLM guard, construct a provider offline,
generate unsolicited workflows, suppress source drift, and ignore source
mtimes. Each mutation ran in its own fresh copy. Hashes of the actual source
files stayed unchanged during those probes. The wheel regression also failed
when the END boundary bug was restored.

An initial full run lacked an activated environment: subprocesses could not
find bare `python` or `ruff`, causing 31 failures. Activating the existing
virtual environment resolved those failures without changing code or tests.
The passing suite still has the skips, expected failure and warnings above;
it is not an all-tests-executed or warning-free claim.

## Operational limits

Existing target files and schedules are preserved. Selecting the offline
profile does not convert an earlier installation or disable an existing
workflow. Generated guidance warns about this distinction. To adopt a new
offline target, use the target skill or the launcher with an absolute path:

```sh
python3 -I -B /Users/raptor/aef-core/scripts/target_repo.py '/absolute/path/to/target'
```

Source manifests verify the two observed boundary states. They exclude access
times and arbitrary symlink destinations, do not identify who caused drift,
and cannot rule out intervening writes that were restored. The launcher is
not an OS sandbox. The target skill additionally requires a baseline and
comparison around the entire semantic integration, not only the launcher.

Policy denial, HITL, injected Services, deterministic replay and disabled
evolution remain in force. No paid/live model evaluation or autonomous lesson
activation was performed. The design rationale is
[ADR 0207](../adr/0207-offline-adoption-and-source-integrity.md); the bounded
authorization and completion criteria are in
[the goal prompt](../../MODEL_REVIEW_GOAL.md).
