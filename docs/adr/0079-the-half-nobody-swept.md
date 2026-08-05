# ADR 0079: The half nobody swept

## Status
Accepted. Phase 2 round 4 — the two areas never examined: the security layer,
and the **non-loop** half of adoption. The loop half had been swept three
times. This half had not been swept once, and it does not work end to end.

## The worst finding: deleting a human-approval gate scored as an improvement

`docs/autonomy/self-improving-loop.md` and every generated `AGENT_INTEGRATION.md`
name removing a HITL gate as a HARD-STOP. Reproduced against the real gate
stack, a candidate that deletes `requires_human_approval=True` from an edge:

```
incumbent (gate ON) : terminated=false, score 0.0
                      HumanApprovalRequiredError: edge 'a' -> 'deploy' requires human approval
candidate (gate GONE): terminated=true, plan_status=done, score 1.0

G2 regressed = False        (incumbent didn't pass, so nothing to regress from)
G3 score      0.0 -> 1.0    (a maximal improvement)
G4 findings   0
```

**Three gates, zero catches, on a maximal reward signal for removing a safety
control.** Two independent causes:

1. `scenario_runner` supplies no `hitl_approvals`, so a HITL-gated incumbent
   *always* crashes and scores 0 — and `Comparison.regressed` short-circuits
   on `not incumbent.passed`.
2. G4 scanned only the candidate, for the literal `=False`. `flag in kwargs`
   is false when the kwarg is simply **deleted**, and the constructor default
   is off. Writing `=False` was a security event; deleting the line was
   invisible. `0`, `[]` and `""` also slipped through, because the check was
   `is False` — identity — while the executor tests truthiness.

Fixed by making G4 compare **base against head**: a control that was on at
the base ref and is not on in the candidate is a finding, however it was
turned off. Removal cannot be seen by scanning only what remains. Verified
against all five evasions plus two controls that must not fire.

## `policy_engine` was dropped at every construction site

ADR 0075's defect, one service over. Every adopter's generated `CLAUDE.md`
says *"`aef/security/tool.py` — the policy engine every tool call passes
through"*, and the CrewAI checklist tells adopters to move tool definitions
behind `aef.security.tool.Tool`. An agent that does so calls
`services.require_policy_engine()`, which **no harness path wired**:
`scenario_runner`, `aef run`, `aef loop record` and harvest's determinism
re-check all built a `Services` without it.

Same consequences, reproduced: `ServiceNotConfiguredError` on every scenario,
candidate and incumbent and all five cohort members at 0.0, G3 rejecting
forever; harvest silently promoting nothing because the re-execution check
read the crash as non-determinism. And the same structural reason it was
invisible: `agents/demo/graph.py`, the only agent the gates are exercised
against, makes no policy-gated call.

All four sites now wire a deny-by-default `PolicyEngine()`. Denials are then
**recorded rather than fatal**, which is what makes `Outcome.policy_denials`
a real regression signal instead of a column of zeroes.

## The onboarding half

Every command in the generated `AGENT_INTEGRATION.md`'s "Start (5 steps)"
except `aef doctor` failed in a freshly adopted repo, and `aef doctor` passed
only because it checked almost nothing.

- **Step 1 failed.** `pip install -e ".[dev]"` installs *this* repo, and
  `aef adopt` writes no `pyproject.toml`. `adopt_loop.py` already carried a
  verbatim diagnosis of this exact bug — the fix had been applied to the
  generated CI workflow and not to the human-facing template. The knowledge
  existed in the codebase and never crossed the seam.
- **The prescribed green bar failed 4/4**, including `mypy --strict aef` —
  ADR 0069 defect 3 verbatim, reinstated in prose. It had been fixed in the
  Copilot and Cursor entry files and not in the two the kit calls canonical.
- **`aef adopt` generated a repo failing its own `ruff check .`** (the shim
  imported `END` and never used it), and `aef init` generated a file
  non-conforming to ruff's default line length, because the template was
  written at aef-core's 100.
- **`aef doctor` exited 1 on a pristine `aef init` repo** — which writes no
  CLAUDE.md by design — while the kit says "fix any [FAIL]". The only fix was
  hand-writing the file the tool should have produced.
- **`aef doctor` passed on an `aef_adapter.py` that was not valid Python**,
  despite adopt promising it "confirms the config and imports are wired". It
  now parses the adapter (parses, not imports — importing an adopter's shim
  would execute their legacy entrypoint as a side effect of a diagnostic).
- **`aef` shipped no `py.typed`**, so `mypy --strict` against `aef` was
  impossible downstream — the green bar this project mandates for adopters
  could not be passed by them. Invisible here, because aef-core type-checks
  its own source tree rather than the wheel.
- **doctor's `empty_objectives` advisory could not fire on the placeholder
  adopt itself writes** (`objectives: "TODO: ..."` is non-empty). A check
  built to catch "the agent has no stated purpose" missed the one string that
  ships by default.
- **The documented `aef run` → `aef eval` sequence cannot work**: without
  `--checkpoints-dir` the run is discarded, and `aef eval` blames the run id
  rather than the missing flag on the previous command.

## What we are not fixing, and are now saying out loud

Of the five per-agent fields, **only `model_provider` reaches a run.**
`aef/config/factory.py` ships one builder. `objectives`, `policies`, `tools`,
`evaluator.suites` and `knowledge_graph` validate and are then ignored — the
Phase 2 config surface (ADR 0014). `extends: _base` is likewise declarative;
nothing resolves a base config, and a nonexistent base raises nothing.

That deferral is fine. What was not fine is that **no generated file said
so**, while the checklist made "fill in these fields" a required step and
doctor called the result "valid". An adopter setting
`policies.require_hitl_above_risk` believed it was enforced; it is not, and
the engine's own default applies instead. The `aef.yaml` stub now states
exactly which fields reach a run and which do not, field by field.

Also recorded and unfixed: `InMemoryAuditLogWriter` is the only writer
shipped, so the audit trail does not survive the process, and the default
writer is stored on a private attribute with no accessor. `docs/roadmap.md`
lists `AuditLogWriter` under Phase 1 DONE — the interface is done, durable
persistence is not.

## The structural finding

`tests/cli/test_adoption_sequence.py` opens: *"This test performs the whole
documented workflow against a real adopted repo, so an instruction that stops
working fails here rather than in someone's repo."* **It does not.** It
exercises only the loop half, and its fixture hand-writes
`agents/mine/graph.py` and `tests/test_smoke.py` — manufacturing precisely
the two preconditions a real `aef adopt` output lacks.

That fixture is why five of these survived a 984-test green suite: *the
guard for the adoption path validates a hand-repaired copy of the thing it is
guarding.* This is the same lesson as ADR 0074's ("a test that constructs the
object under test cannot see a defect in how the shipping caller constructs
it"), arriving through a fixture rather than a constructor.

## Confidence
High on each fix: reproduced by running, re-run against the failing case, and
the full onboarding path now goes `aef adopt` → `aef doctor` exit 0 with the
generated repo passing the lint the kit prescribes, and `aef init` → `aef
doctor` exit 0. **Not claimed:** that the security layer is swept. One area
was examined in one pass and yielded a maximal-severity finding; that is not
evidence the rest is clean.
