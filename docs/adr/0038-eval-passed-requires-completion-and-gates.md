# ADR 0038: `EvaluationRecord.passed` requires task completion AND all domain gates

## Status
Accepted

## Context
Round-2 test-suite-integrity audit found a real latent bug in
`EvaluationRecord.passed`:

```python
return all(self.domain_gates.values()) if self.domain_gates else self.task_completion >= 0.5
```

The moment *any* domain gate is configured, `task_completion` — and the
`errors` that drive it to `0.0` — are ignored entirely; `passed` becomes
`all(gates)` alone. Reproduced directly: `EvaluationRecord(task_completion=
0.0, domain_gates={"sharpe_gate": True}).passed` returned `True`. An
errored or incomplete run was marked "passed" purely because a domain gate
(e.g. a Sharpe threshold) happened to hold.

Domain gates are one of the five per-agent surfaces and feed the
self-improvement loop directly (a rule-based critic/judge acts on `passed`).
A false "passed" on an errored run is exactly the kind of silently-wrong
signal the whole session has been removing — and the existing eval tests
only exercised gates at `task_completion=0.5`, so the interaction was
unpinned in either direction.

## Decision
`passed` now requires **both**: the task completed (`task_completion >=
0.5`) **and** every domain gate holds (`all(domain_gates.values())` — which
is vacuously `True` when no gates are configured, preserving the
no-gates behavior). Domain gates are additional *hard* constraints layered
on top of task completion, not a replacement for it.

## Consequences
- An errored/incomplete run can no longer be marked `passed` because a gate
  happens to hold — completion is a floor that gates add to, never remove.
- A completed run with a failing gate is (still) not passed; a completed run
  with all gates holding is passed; a no-gates run passes on
  `task_completion >= 0.5` as before — all three now pinned by tests.
- Existing eval tests are unaffected: they exercise gates at
  `task_completion = 0.5` (a no-plan, no-error state), which is `>= 0.5`, so
  a passing-gate run still passes and a failing-gate run still fails.
- 318/318 tests (one new, pinning all three combinations of
  completion × gate), mypy --strict clean, ruff clean.

## Alternatives Considered
- **Keep gates-only when gates are present** (the old behavior), documenting
  that domain gates fully override task completion. Rejected: it makes
  `passed` mean two incompatible things depending on config, and lets an
  errored run pass — the failure mode found. Gates as an *additional*
  constraint is the single coherent semantics.
- **Require `task_completion == 1.0` (not `>= 0.5`) when gates exist.**
  Rejected: that changes the completion threshold as a side effect of
  configuring a gate, another config-dependent meaning shift. The `>= 0.5`
  floor is the existing, documented completion bar; gates add to it, they
  don't move it.

## Confidence
High — the errored-run-marked-passed case was reproduced before the fix,
the fix pins all three completion × gate combinations, and every existing
eval test still passes (the change only tightens the gates-present branch,
which was previously untested for a non-passing task_completion).
