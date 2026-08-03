# ADR 0006: Evolution engine ships disabled by default, with the disablement enforced in code, not just documentation

## Status
Accepted

## Context
Constraint #7 of the build task is explicit: "No autonomous
self-modification in this repo yet. Build the evolution engine's
interfaces, archive store, eval gate, canary controller, and rollback
path — but ship it disabled behind `evolution.enabled: false` with a
comment explaining the Phase 4 gate criteria." Both source documents
independently identify self-modification as the single largest risk in
the entire architecture (report §24 Risk Analysis: "self-modification
instability"; blueprint Risk Analysis: "the single greatest hazard in the
entire design is an evolution engine that convinces itself a regression is
an improvement"). A config flag alone (`enabled: false` in a YAML file) is
a weak control — anyone editing the file can flip it, and nothing enforces
that flipping it is actually safe.

## Decision
Enforce the disablement at two layers, both raising hard errors rather
than silently accepting the flag:
1. `aef.evolution.engine.EvolutionConfig` — its `__post_init__` raises
   `NotImplementedError` naming every unmet Phase 4 gate criterion
   (shadow execution, null-hypothesis baseline, golden-trace regression,
   bounded mutation rate, cumulative-drift monitoring, canary rollout,
   HITL approval) if constructed with `enabled=True`.
2. `aef.config.schema.EvolutionSettings` — a pydantic `field_validator`
   rejects `enabled: true` in any `aef.yaml` at config-load time, with a
   readable `ValidationError` rather than a traceback from deep inside the
   evolution engine.

Every class in `aef/evolution/engine.py` (`MutationProposer`,
`ArchiveStore`, `EvalGate`, `CanaryController`) is a real ABC whose
abstract methods raise `NotImplementedError` referencing "evolution is
disabled" — there is no code path in this repo, at any layer, that
performs an autonomous graph mutation.

## Consequences
- Re-enabling evolution later requires either (a) shipping real
  implementations that satisfy all seven gate criteria and removing this
  hard block, or (b) deliberately weakening this ADR's decision — which
  itself becomes a visible, reviewable change (a diff to a `__post_init__`
  and a `field_validator`), not a one-line config edit.
- Phase 4 work has a concrete, enumerated definition of "done": the seven
  gate criteria listed in `aef/evolution/engine.py`'s module docstring.

## Alternatives Considered
- **A plain config flag with no code-level enforcement, as constraint #7
  literally reads.** Rejected as insufficient — the letter of the
  constraint is satisfied by a flag, but the *intent* (this is the
  architecture's single greatest hazard) calls for a control that can't be
  silently bypassed by editing YAML.
- **Omit the evolution module entirely until Phase 4.** Rejected: the
  build task explicitly asks for the interfaces, archive store, eval gate,
  canary controller, and rollback path to exist now, as typed stubs.

## Confidence
High — this is a deliberately conservative reading of a safety-critical
constraint, and both source documents' own risk analyses support erring
toward over-enforcement here.
