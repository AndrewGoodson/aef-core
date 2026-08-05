# ADR 0091: One list instead of four

## Status
Accepted. Phase 3 round 4. This ADR exists because the same defect happened
four times and I kept fixing instances of it.

## The defect, four times

| ADR | What was missing | Where |
|---|---|---|
| 0073 | `critic`, `judge` | `aef run` — so LOOP.md obligation 2 made obligation 3 impossible |
| 0075 | `critic`, `judge` | `scenario_runner` — the fix had reached two of three sites |
| 0079 | `policy_engine` | all four sites |
| 0089 | (a deep-copy raise) | same symptom, different route |

Every time the symptom was identical. A service the node needs is absent in
the gate path; `scenario_runner` swallows the `ServiceNotConfiguredError`;
candidate, incumbent and all five cohort members score **0.0**. So G3 rejects
every candidate forever while `aef loop doctor` reports the agent green.

Measured before this change: `aef run` wired **7 of 8** requirable services,
the gate path wired **4**. A node calling `require_tracer()` or
`require_durability()` worked in production and failed in the gate. And
`evaluator` had a `require_` method, no setter anywhere, and a migration
checklist telling adopters to "add an Evaluator" — an instruction with no
working destination.

## Decision

`aef/services/runtime.py::agent_services()` is the one list. All four sites
call it: `scenario_runner`, `harvest`, `aef run`, `aef loop record`.

Callers override what legitimately differs — a durable memory store versus a
throwaway one, a scenario's pinned clock versus a real one — and inherit the
rest. **`model_provider` is the only service the two paths differ on**, and
that difference is real: the gate sandbox has no credentials, and a node that
calls a model is `deterministic=False` and unreplayable anyway. It is
asserted as the only exception, so adding a second is a deliberate act.

`memory` and `durability` default to in-memory rather than absent. Present,
so a node can require them; throwaway, because a gate re-execution must not
write to the adopter's stores — that would let a gate run mutate the evidence
a later proposal is built from.

## Why the test is a source assertion, and why that is right here

`test_every_construction_site_goes_through_the_one_factory` greps for
`agent_services(`. ADR 0078 said a source-string assertion is "a comment the
test runner checks", and that criticism stands where the property is a
behaviour.

Here the property **is** "these modules call that function". A site that
builds its own `Services(...)` is precisely how the list drifted four times,
and no behavioural test can see a site that has not been written yet. The
behavioural half exists alongside it: every requirable service is exercised
end to end through `run_scenario`, and the parametrisation is derived from
`Services` itself, so a service added later joins the test without anyone
remembering to.

## Confidence
High: all eight requirable services now behave identically on both paths,
verified by running a node that calls each one. **Not claimed:** that
`agent_services` has the right defaults for every adopter. It has defaults
that make an agent runnable; an adopter whose nodes need a real
`model_provider` in the gate has a problem this does not solve, and the
honest answer there is that such a node cannot be gated deterministically at
all.
