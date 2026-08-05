# ADR 0082: A policy you can configure and cannot widen

## Status
Accepted. Phase 2 items 2a and the security half of 2d.

## Context

Two halves of one problem, from ADR 0079 and ADR 0080.

**The config did nothing.** `policies.require_hitl_above_risk` and
`tools.allow` validated — with a range check that exists specifically so a
clean config cannot build an invalid runtime `PolicyConfig` — and were then
ignored. `aef/config/factory.py` shipped one builder. An adopter setting a
HITL threshold believed it enforced and got the engine's own default instead.
The generated `CLAUDE.md` meanwhile told them the policy engine is *"the
engine every tool call passes through"*.

**The gate ran a policy nothing matched.** ADR 0079 wired
`PolicyEngine()` — bare, deny-by-default — into the gate so a policy-gated
agent would run at all. That fixed the crash and left the measurement
meaningless: every adopter tool call is denied under it, so
`Outcome.policy_denials` saturates on candidate and incumbent alike and can
never differ. A regression signal that is always equal on both sides is not a
signal.

## Decision

`build_policy_config(tools, policies)` maps config to runtime, and `aef run
--config`, `aef loop gate --config` and `aef loop cycle --config` all use it.

**`tools.allow` is a list of scopes, not tool names.** The engine gates on
`tool.required_scopes`, so a name allowlist could not authorise anything —
every tool would still be denied for missing scopes and the field would do
nothing. Names are the *deny* axis (`policies.forbid`), because a name is the
right handle for "never this one" and a scope is the right handle for "this
capability is permitted". Stated in the generated stub, because the field name
alone does not say it.

Deny-by-default survives being configurable: an empty `tools.allow` allows
nothing, which is exactly what an unconfigured engine answers.

## The part that matters — the gate reads it from the base ref

`aef.yaml` is Zone C: not agent-writable, so a candidate diff touching it is
already rejected. That is not sufficient reason to read it from the
candidate.

The gate reads config the way it reads every other rule it judges by —
`git show <base_ref>:aef.yaml`. The arithmetic is `trust.py`'s and ADR 0044's:
**if an agent can modify what judges it, the judgement carries no
information.** A defence that rests on "the zone check will catch it" is one
layer deep; this is the second layer, and the two are independent.

The policy then reaches the sandbox **as data** — a `_policy.json` the
harness writes into the workspace and passes as `argv[3]` — rather than the
runner reading `aef.yaml` from the workspace it is executing. Same reason:
the workspace is the candidate's tree.

Verified against a planted fault. A candidate branch that grants itself a new
scope, empties the deny list and raises the threshold to 0.99:

```
BASE policy   : scopes=['safe.read'] forbid=['rm_rf'] hitl=0.1
after widening: scopes=['safe.read'] forbid=['rm_rf'] hitl=0.1
```

And the control, because a reader that always returned the same thing would
pass that test and be useless — an owner's change on the base ref *is* seen:

```
owner change on main: scopes=['owner.added', 'safe.read']
```

An unreadable or unparseable config returns `PolicyConfig()` — deny-by-default
— never "no restrictions". A config that fails to load must not become the
most permissive state available.

## What is still not wired

`objectives`, `evaluator.suites`, `knowledge_graph` and `extends`. Those stay
deferred (ADR 0014), and the generated stub now separates "wired" from "still
not wired" field by field rather than declaring the whole surface inert.

`objectives` deserves a word: the config field and the required `--objective`
flag are two things with one name and no connection. That is a naming defect,
not a wiring one, and fixing it is a rename an owner should approve.

## Consequences
- Adopters must pass `--config` to get their policy. Without the flag the
  engine falls back to deny-by-default, which denies every tool call — the
  same behaviour as before this change, so nothing silently loosens.
- `Outcome.policy_denials` becomes a real regression signal for the first
  time: candidate and incumbent now run under the owner's actual policy
  rather than under a total-denial policy neither would ever meet.

## Confidence
High on the trust property: reproduced with a planted fault and with the
control that proves the reader is not inert. **Not claimed:** that
`tools.allow`-means-scopes is the reading every adopter will expect from the
name. It is the only reading under which the field does anything, and it is
documented, but the name is a poor one and a rename is worth considering.
