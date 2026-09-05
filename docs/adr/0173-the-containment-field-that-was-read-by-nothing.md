# ADR 0173: The containment field that was read by nothing

## Status
Accepted. Fix worker H2 of the upgrade loop, closing R5 of the second seam
hunt. Model: Opus (session default). Zero live model calls.

## Context

ADR 0161 shipped `shadow.containment: auto|fallback|off`, a `ShadowConfig`
that validates the three strings and refuses a fourth, a
`build_containment_mode` that turns the string into the enum the harness runs
on, a test asserting the config strings and the enum cannot drift, and a test
asserting the config default is the contained one.

R5 is that none of it was connected:

```
$ grep -rn "shadow_for(\|build_containment_mode(" aef/
aef/config/factory.py:185:def build_containment_mode(...)   <- the definition
aef/harness/shadow.py:691:def shadow_for(...)               <- the definition
```

`build_containment_mode` had zero callers. `shadow_for`'s `mode` parameter
defaulted to `ContainmentMode.AUTO` in the signature. So the one wire that
carries an owner's declared mode from `aef.yaml` to the run was the one wire
nobody had connected, and the surface read as wired: the field validated, the
error message on a typo was excellent, and the value went nowhere.

## Reproduction, before anything changed

`<scratch>/repro.py`, an integrator doing exactly what `shadow_for`'s
signature invites — threading the config's `image` through, because `image` is
the only shadow field the signature names as coming from config:

```
aef from: .../worktrees/agent-a5fa46dfb275cdc00/aef/__init__.py
owner wrote  : shadow.containment = 'off'
owner wrote  : shadow.image       = 'aef-worker:test'
run got      : decision.mode      = auto
run got      : decision.contained = True
run got      : decision.reason    = contained by docker with image aef-worker:test; isolation verified
run got      : owner_opted_out    = False

=== ARM 2: owner wrote `fallback`, box has no container runtime ===
owner wrote  : shadow.containment = 'fallback'
run got      : UncontainedShadowError: shadow containment is unavailable: no container runtime found. shadow.containm ...

FINDING: the owner declared `off`; the run executed `auto`. The owner
         who declared `fallback` got `auto`'s refusal.
         build_containment_mode() is the one wire that carries the
         choice, and nothing calls it.
```

Both directions of the gap, run. Arm 1 is the harmless one: the owner asked
for less containment and got more. Arm 2 is the one that costs work — an
adopter with no container runtime writes the mode that exists precisely for
them and gets the refusal it exists to avoid.

## The decision

**`shadow_for`'s `mode` has no default, and neither does
`resolve_containment`'s.** This is ADR 0101's rule applied to a parameter
rather than a module: a default that silently overrides the owner's config is
a promise the signature makes and the code breaks, and an unkept promise in a
typed signature is worse than an honest absence. `ContainmentMode.AUTO` as a
default reads as "the safe default" and was in fact "your `aef.yaml` is
ignored". The caller now says which mode, or does not compile.

`resolve_containment` is pinned for the same reason one level down. It is the
function that turns the owner's choice into a `ContainmentDecision`; a default
there is the same defect with one more frame between it and the owner.

**One derivation.** `RunConfig` — the single construction site every
config-driven command already reads (`aef run`, `aef loop bootstrap`) — gains
`containment_mode`, set by `build_containment_mode(config.shadow)`. When a
caller for shadow execution is written, there is exactly one place it reads
the owner's choice from. Its unconfigured value is DERIVED from
`ShadowConfig()` rather than written as `ContainmentMode.AUTO`, so "no
`aef.yaml`" and "an `aef.yaml` with no `shadow:` block" cannot drift into two
different security postures — which would be ADR 0091's shape reintroduced by
the fix for it.

## The reproduction, after

`<scratch>/repro2.py`:

```
owner wrote  : shadow.containment = 'off'
RunConfig    : containment_mode   = off
run got      : decision.mode      = off
run got      : decision.contained = False
run got      : owner_opted_out    = True

=== ARM 2: owner wrote `fallback`, box has no container runtime ===
RunConfig    : containment_mode   = fallback
run got      : decision.mode      = fallback
run got      : decision.reason    = no container runtime found
run got      : it RAN             = True

=== ARM 3: omitting `mode` ===
run got      : TypeError: shadow_for() missing 1 required keyword-only argument: 'mode'
```

## What this does NOT do

**It does not add a production caller for shadow execution.** ADR 0161's
"Undone" said shadow execution has no production caller; that is still true,
and adding one is a design decision rather than a patch. What a caller would
need, from the trust case's §2.1 on live-input shadowing:

- a worker image containing the adopter's own `aef` and its dependencies —
  this repo has none to ship, which is why `shadow.image` has no default;
- a decision about which live requests may be duplicated onto a candidate,
  since a node declaring `EXTERNAL_CALL` makes that call for real, twice;
- an owner who has read that the workspace is a writable host directory, and
  that `assert_shadowable` refuses a MUTATING candidate contained or not.

This increment makes the wire exist and refuses the silent default. It does
not decide any of the three above.

The `shadow.containment` field is therefore still, today, read by exactly one
thing: `RunConfig`. That is stated in `RunConfig`'s own docstring rather than
covered over. It is not the kind of promise ADR 0101 deleted — the wire is
five lines, it is exercised end-to-end by tests through `shadow_for` against
real `ContainmentDecision`s and a real ledger, and its absence was a live
defect rather than a deferred feature.

**No control was weakened.** `auto` still refuses rather than falling back;
the fallback is still reachable only by an owner writing it in `aef.yaml`; the
single `uncontained=True` call site in `aef/` and the AST scan that allows
exactly one are untouched. What changed is that an owner writing `fallback`
now reaches it.

## Does S5's +1 on dimension 4 survive this finding?

**Yes, and the argument is about which direction the gap failed in.**

The gap applied `auto` — the CONTAINED-or-refuse path — regardless of what the
owner wrote. Nothing weaker than `auto` was reachable through it. The owner
who wrote `off` got a container they had declined; the owner who wrote
`fallback` got a refusal instead of an uncontained run. So no run was ever
less contained than ADR 0161 claimed, and the scored property of dimension 4 —
*is the shadow contained by default, and is weakening it an explicit, recorded
owner choice* — held in fact, and held more strictly than documented, because
the opt-out did not work either.

The contrary case, stated because it is not frivolous: ADR 0161's own text
says "the fallback is kept, named and logged, and reached only by an owner
writing it in `aef.yaml`", and an owner writing it in `aef.yaml` reached
nothing. A false sentence in an accepted ADR is exactly what a rubric score
should not rest on. Two things follow from that, and only one of them is a
deduction:

1. The sentence is wrong about REACHABILITY and is corrected by an erratum on
   0161 (below). That is a documentation defect, and it is fixed here.
2. It is not wrong about CONTAINMENT, which is what dimension 4 measures. The
   overstatement was in the permissive direction of the config surface, not
   the permissive direction of the control.

There is one real cost, and it belongs to the audit trail rather than to
containment: `owner_opted_out: True` in the ledger was unreachable from a
config-driven run, so the distinction the `ContainmentDecision` draws between
"a shortfall" and "a choice" could only ever be written by a test. That
distinction now has a path an owner can take, and the three config-path tests
below assert it end-to-end.

**Verdict: dim 4 keeps its 15, delta 0. No rubric change.**

## Mutations: 5 perturbed, 5 detected

Each restored from a shasum-verified byte backup; every restore re-verified
with `shasum -a 256 -c`.

| # | mutation | result |
|---|---|---|
| M1 | `shadow_for`'s `mode` default restored | CAUGHT — 1 failed |
| M2 | `resolve_containment`'s `mode` default restored | CAUGHT — 1 failed |
| M3 | `build_run_config` stops reading `config.shadow` | CAUGHT — 2 failed |
| M4 | the unconfigured default becomes a literal `FALLBACK` instead of `ShadowConfig()`'s | CAUGHT — 4 failed |
| M5 | `build_containment_mode` ignores the config it is handed | CAUGHT — 2 failed |

M1's first form failed for the wrong reason and the TEST was rebuilt rather
than the mutation dropped. The guard originally called `shadow_for` without
`mode` and expected `TypeError`; with the default restored that call proceeds
to build a real container and dies much later with
`IsolationError: worker for 'unused:build_graph' exited before describing its
graph`. The test failed, but on a cause unrelated to the property — the rule
0161's M5 note records. The guard now reads `inspect.signature`, which is
exactly the property being pinned, and the mutation flips it directly.

## Green bar

`pytest -q`: **2269 passed, 5 skipped** (+5 tests, none removed).
`mypy aef examples`: clean, 132 source files.
`ruff check .` and `ruff format --check aef tests examples`: clean.

Files touched: `aef/harness/shadow.py` (two signatures, two docstrings),
`aef/cli/run.py` (`RunConfig.containment_mode` + `build_run_config`),
`tests/harness/test_contained_shadow.py`, `tests/harness/test_trust_case.py`
(one call site). No `PolicyEngine`, gate, schema, or Tier-1 code was touched.

## Consequences

`shadow.containment` is read by something. The next person to write a shadow
caller reads the owner's mode from `RunConfig.containment_mode` and cannot
forget to, because there is no default to forget it into.
