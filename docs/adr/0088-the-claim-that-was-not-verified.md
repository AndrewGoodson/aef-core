# ADR 0088: The claim that was not verified

## Status
Accepted. Phase 3 round 3 — the adversarial round against the same night's
own commits. It defeated ADR 0085, written four commits earlier.

## What ADR 0085 claimed

> The only way to emit exactly one forged marker is to stop the runner
> emitting its own, which needs `os._exit`, which needs an import G0
> rejects — and G0 now runs before any candidate code executes. Three
> independent layers, and none of them is "the candidate did not think of
> it."

**That is false, and I wrote it as though verified.** I tested the two
suppression routes I had thought of, both built on a top-level `import os` /
`import sys`, and generalised from two data points to "the only way".

## The attack

`aef` is on `DEFAULT_IMPORT_ALLOWLIST` — a Zone A graph legitimately needs
`aef.kernel` and `aef.state` — and the allowlist matched on **root module
only**. So:

```python
from aef.harness import scenario_runner as _m
_m.sys.__stdout__.write(_m.result_marker(_m.sys.argv[3]) + FORGED_JSON)
_m.sys.stdout = _m.sys.stderr
```

A module object is shared process-wide. Importing the harness hands agent
code `sys` — including `argv`, which carries the per-run nonce, and
`__stdout__`, which is the real fd 1 whatever `sys.stdout` has been pointed
at. The runner's own `print` then goes to stderr, which `_parse` never reads.

**Exactly one marker. Zero G0 findings. All six gates passed on a broken
agent**, with the forged payload generated from `_scenarios.json` so it
reported `not passed` for `must_fail` scenarios and the ADR 0060 tripwire
never fired either.

The two layers ADR 0085 called independent were not. Both rested on `sys`
being unreachable, and `aef` on the allowlist broke that.

## Decision

Two changes to G0, both narrowing reach rather than adding a check the
attacker must fail to think of:

- **`aef.harness` and `aef.cli` are denied to Zone A.** Matching is now on
  dotted prefix, not root module. There is no legitimate reason for a graph
  to import the harness that judges it.
- **`os`, `sys`, `subprocess`, `shutil`, `socket`, `importlib` are denied as
  ATTRIBUTES on any object**, alongside `argv`, `modules` and the `__std*__`
  handles. `aef.kernel.durability` imports `os`, so `durability.os` reached
  the filesystem without `os` appearing in any import statement — and
  `aef.kernel` cannot be denied, because that is what agents are built from.

Verified: the exact hijack and four variants are rejected; the imports a Zone
A graph actually needs still pass; **this repo's own demo agent still passes
G0**, which is the strongest control available since it is the agent every
gate test runs against.

## The honest residual

This raises cost. It does not make in-process evidence trustworthy.

The candidate's code and the code reporting on it share a process. Any
channel the reporter can write, the candidate can write. G0 is a static scan
of what a candidate *declares*, and `sandbox.py` states plainly that it
enforces neither network egress nor filesystem confinement. **The containment
is a static allowlist over a shared interpreter, which is a cost barrier and
not a boundary.**

The structural fix is to stop deriving evidence from a process the candidate
executes in — a design change, not a patch, and one an owner should decide.
I am not claiming to have made the evidence trustworthy. I am claiming the
demonstrated path is closed and the class is not.

## What this says about the method

Three nights running, the round that attacked the previous round's own
commits found the most severe defect of that night. That is now a pattern
with three data points, and it is the argument for the round existing.

The specific failure here is narrower and worse than a missed case: **I
asserted an exhaustive claim — "the only way" — from two tested examples,
in an ADR, in the section describing the security property.** The
reproduce-first rule says verify a detector against a planted fault. It did
not say: do not generalise from the faults you happened to plant. It does
now.

## Confidence
High on the fix: the attack was reproduced end to end through the real gate
pipeline before and after, with controls proving the denial does not reject
legitimate agents. **Low on completeness, stated as such this time.** I have
closed the paths I found. I have no basis for saying they are the only ones.
