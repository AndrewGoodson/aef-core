# ADR 0100: Config that means what it says

## Status
Accepted. Milestone 2. Closes the gap ADR 0092 documented and ADR 0014
deferred.

## The problem, restated exactly

Of the five per-agent fields the prime directive allows to differ,
`model_provider`, `policies` and `tools.allow` reached a run. `objectives`,
`evaluator.suites` and `knowledge_graph` validated and were ignored. ADR 0092
documented that, and documentation is not wiring — an owner who read the field
names still had three ways to believe something was configured that no code
would ever read.

Each is resolved one of two ways, and there is no third: **it reaches a run,
or it is refused at load time.**

## `evaluator.suites` -> `domain_gates` (wired)

`RuleBasedEvaluator.domain_gates` is the pluggable per-agent surface report
§16 describes, and it has been a declared injection point with no production
caller since Phase 0 — precisely the shape ADR 0092 named: *a declared
injection point with no production caller is indistinguishable from a missing
feature*.

**A suite is a `module:function` reference, not a bare name.** A bare name
needs a registry someone registered into, which needs an import to have
already happened: invisible, order-dependent, and silent when it did not. The
same shape the loop already uses for `--entrypoint` resolves explicitly and
fails loudly. Both shipped example configs had to change — `agent.azure_sec`
declared the bare name `private_azure_pentest`, which named nothing
resolvable, harmless only for as long as the field was read by nothing.

Applied by `aef run --observations --config` and `aef eval --config`, both
through one `build_evaluator` — one builder per scoring site, for the reason
ADR 0091 records about service lists: two constructions of the same thing
drift, and the drift is invisible until something scores differently in two
places.

**A domain gate can only make a verdict stricter.** `passed` is
`task_completion >= 0.5 and all(domain_gates.values())`, so a gate can refuse
a run that would otherwise pass and can never rescue one that would not.
That is what makes this safe to wire without touching `task_completion`
semantics, which HARD-STOP #6 and ADR 0038 fix. Tested directly: a passing
gate on a run with errors still fails.

## `objectives` (wired)

The config field and the required `--objective` flag were two things with one
name and no connection. `--objective` is now optional and falls back to
`objectives`; the flag still wins when both are present, because a per-run
override is what a flag is for. Neither is an error rather than an empty
objective, which every evaluator would score against nothing.

## `knowledge_graph` (refused)

There is no builder, so the block now raises at load time — the same
treatment `extends` got in ADR 0084, for the same reason.

**The design reason, since the milestone asked for one and not an excuse:** a
knowledge-graph adapter needs a retrieval contract the node signature does not
carry. `Services` hands a node its dependencies, and a KG is only useful if a
node can *ask* it something — which means a query interface, a result shape
the context engine can budget, and a provenance story for retrieved facts.
None of those three exist. A constructor built before them produces a service
nothing can call, which is the defect class ADR 0092 named. Building the
constructor first would look like progress and be the same bug in a new place.

The refusal immediately caught two shipped example configs declaring
`impl: neo4j`. That is the point: they had been claiming a knowledge graph the
runtime never gave them.

## What the adversarial round found

A suite is arbitrary code the config points at and the evaluator calls, so it
is a new attack surface and was probed as one. Four findings, all reproduced:

**A suite could name the judging apparatus.** `aef.harness.loop:gate`
resolved cleanly. G0 forbids agent code importing `aef.harness`/`aef.cli`;
`evaluator.suites` was a second door into the same rooms, reached from a
different direction. Now refused, reading `FORBIDDEN_AEF_SUBPACKAGES` **from
G0** rather than copying it — `aef.harness` imports `aef.config`, so the
import is lazy to avoid a cycle, and a hand-maintained copy would be "drift
between two lists nobody compares" (ADR 0091). Prefix matching is on a dot
boundary, so an adopter's `aef_harnessed` package is not caught by
resemblance.

**A gate returning a non-bool was believed.** `"yes"` landed in
`EvaluationRecord.domain_gates` — typed `dict[str, bool]` — as `'yes'`, and
`passed` read it truthily. Any non-empty string passed; `""` and `0` failed. A
forgotten `return` produced `None` and failed every run for a reason nothing
reported. Now refused with the suite named. A verdict a gate did not actually
give is worse than no gate, because `passed` is what an owner reads to decide
whether to trust a run.

**A raising gate produced an anonymous traceback.** Now wrapped so the error
names the suite; an owner reading it would otherwise blame the evaluator.

**Resolution executes the module body.** Documented, not fixed, and pinned by
a test so it is a known property rather than a later surprise. It is inherent
to `module:function` and identical to what `--entrypoint` has always done.
Containing it needs the sandbox Milestone 4 addresses.

## Consequences

The generated `aef.yaml` stub's `STILL NOT WIRED` section is **gone**, which
was 2d's stated test of whether this milestone happened. It is replaced by a
`REFUSED` section naming `knowledge_graph` and `extends`, because an adopter
who writes a refused block deserves to learn it from the stub rather than from
their first command failing.

One existing test asserted `STILL NOT WIRED` was present. It now asserts the
inverse and pins both directions — a stub that grew the section back would be
describing a regression, and one that dropped the refusals would be hiding
one.

## Confidence
High on the wiring: every claim is tested by sending something down the wire —
a real suite module on disk, resolved through a real `aef.yaml`, applied to a
real run — rather than by asserting the wiring exists.

Lower on the surface this opens. `evaluator.suites` is the first config field
that names code to execute, and three of the four adversarial findings were in
that mechanism rather than in the fields it serves. The module-body execution
is real and unmitigated until Milestone 4.
