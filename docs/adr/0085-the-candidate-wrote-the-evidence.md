# ADR 0085: The candidate wrote the evidence

## Status
Accepted. Phase 3 round 1, sweeping the eval harness and observability. The
most severe defect found in this program.

## The attack

`run_variant` executed the candidate's graph in a subprocess and did
`json.loads(result.stdout)`. **The candidate's own code runs in that
subprocess.** Two added lines inside `build_graph`, containing no import and
nothing on G0's forbidden list:

```python
print('{"s1": {"outcome": {"terminated": true, "plan_status": "done", ...}, "score": 1.0}}')
raise SystemExit(0)
```

`SystemExit` is a `BaseException`, so it sailed through `load_graph`'s
`except Exception` and exited the process **cleanly**, with the forgery as
its entire stdout. The real agent — which errors on every scenario — never
ran.

Reproduced through the real runner:

```
honest (agent errors out)    score=0.0  plan_status=None  errors=1
forged (2 added lines)       score=1.0  plan_status=done  errors=0
```

and through the full pipeline, all six gates passing on a broken agent.

**This is strictly stronger than ADR 0060's reward hack.** There the agent
ran and lied about its plan status; the corpus was still a real observation
of something. Here the candidate authors the observation. That defeats
ADR 0060's own stated escape hatch — *"detection requires either ground
truth, or an observation of the work that the agent does not author"* —
because a `MUST_FAIL` tripwire is compared against the forged `Outcome` too.

## The second half: G0 ran after the candidate

`_gates_with_evidence` was called **before** `run_pipeline`. Building
evidence executes the candidate — N+2 corpus passes in subprocesses — so
G0's import allowlist, the control that exists for exactly this, ran second.

`gates/base.py` states the opposite as the design: *"All four cheap gates run
before the expensive corpus re-execution in G2. G4 is deliberately early: a
proposal reaching for its own tests is rejected before it gets to run
them."* It was not true. Reproduced: a candidate with `import socket` and a
module-level write to an absolute path outside the workspace had already
written its marker by the time G0 rejected it.

`sandbox.py` is explicit that it enforces neither network egress nor
filesystem confinement, which is exactly why G0's allowlist is the control
here — and it was running after the thing it controls.

## Decision — three independent layers

1. **`load_graph` catches `BaseException`.** Agent-authored code does not get
   to decide the process is finished.
2. **The result is framed by a per-run nonce, and the harness requires
   EXACTLY ONE marker.** The nonce is in argv, so a candidate *can* print a
   valid-looking marker — and then there are two, and two is not one. That is
   reported as a security event, not a bad candidate.
3. **The cheap gates run first.** `gate()` now runs G0/G1/G4/G5 as one pass
   and builds evidence only if they all pass. Canonical order is unchanged;
   a rejected candidate never executes.

Verified end to end: the hostile candidate's marker file does not appear,
`gates that ran: ['G0']`, and the ledger records *"not built: G0 rejected the
candidate first, so its code was never executed"*.

This also closes ADR 0078's cost finding — N+2 corpus passes were being spent
on candidates a cheaper gate had already rejected — but that was never the
reason to do it.

## What layer 2 cannot do, stated rather than assumed

A candidate that forges the marker **and** prevents the runner writing its
own — `os._exit`, uncatchable by any handler — produces exactly one marker
and the parse layer cannot tell. It is stopped by layer 3: `os` is not on the
import allowlist and G0 now runs first.

A test pins **both halves** of that: that the parse layer is fooled, and that
G0 rejects it. A defence that rests on the attacker not thinking of something
is not a defence, and a limit that is not written down gets assumed away.

## Consequences
- `scenario_runner` takes a nonce argument; anything invoking it directly
  must pass one.
- A candidate rejected by a cheap gate is now never executed at all, which
  changes what the ledger's evidence note says for those runs.

## Confidence
High on the attack and on each layer: every variant was run against the real
runner before and after, including the two the fix does not catch at the
parse layer. **Not claimed:** that this closes candidate-authored evidence in
general. The candidate still shares a process with the reporter, and the
containment rests on G0's allowlist being complete. That is a much narrower
claim than "the evidence is trustworthy", and it is the honest one.
