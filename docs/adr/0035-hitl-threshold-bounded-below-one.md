# ADR 0035: `PolicyConfig.require_hitl_above_risk` is bounded to [0.0, 1.0)

## Status
Accepted

## Context
Round-1 line-by-line security audit found the residual half of ADR 0025's
asymmetry. ADR 0025 bounded `ToolCall.risk` to `[0.0, 1.0]` and added a
finite guard to `PolicyConfig.require_hitl_above_risk`, but never added a
*range* guard to the threshold. Because risk is capped at 1.0,
`PolicyEngine._decide`'s gate `call.risk > require_hitl_above_risk` is
unreachable for any threshold `>= 1.0` — the single most dangerous call
(risk exactly 1.0) then returns `ALLOW` instead of routing to
`REQUIRE_HITL`. Reproduced directly: `PolicyConfig(require_hitl_above_risk=
1.0)` evaluating a `ToolCall(risk=1.0)` returned `PolicyDecision.ALLOW`, and
`1.5` was accepted without complaint.

`require_hitl_above_risk=1.0` is an easy, natural-looking "only require HITL
at max risk" misconfiguration — and it fails toward `ALLOW`, the dangerous
direction, for exactly the highest-risk call, silently disabling the
containment gate this module exists for (constraint #6).

## Decision
`PolicyConfig.__post_init__` now rejects a `require_hitl_above_risk` outside
`[0.0, 1.0)`. The half-open upper bound is deliberate: since risk is capped
at 1.0, the threshold must be *strictly below* 1.0 for the gate to remain
reachable — at 0.999 a max-risk 1.0 call still routes to `REQUIRE_HITL`. To
hard-*deny* a tool rather than gate it, use `forbidden_tool_names` or
withhold its scopes; the risk threshold is a gate, not an off switch.

## Consequences
- A max-risk call can no longer silently `ALLOW`: the gate is always
  reachable because no valid threshold can sit at or above the risk ceiling.
- Every existing config is within bounds (default `0.0`; the shipped
  `agent.azure_sec.yaml` uses `0.7`) — verified, pure tightening, no config
  needed updating.
- 305/305 tests (three new: reject `>= 1.0` and `< 0.0`, and an end-to-end
  proof that risk 1.0 at threshold 0.999 routes to `REQUIRE_HITL`), mypy
  --strict clean, ruff clean.
- Completes the ADR 0025 lineage — both the risk value and its threshold are
  now range-bounded on the same principle (a NaN/out-of-range value silently
  breaks a `>` comparison and the value's own docstring already documented
  the intended range).

## Alternatives Considered
- **Bound to the closed `[0.0, 1.0]`.** Rejected: it rejects `1.5` but still
  accepts `1.0`, which is precisely the footgun — a threshold equal to the
  risk ceiling leaves the gate unreachable. The half-open bound is what
  actually closes the bypass.
- **Clamp an out-of-range threshold instead of rejecting.** Rejected, same
  reasoning as ADR 0022/0025: silently substituting a different (wrong)
  security threshold is worse than a loud rejection at construction.

## Confidence
High — the `ALLOW`-at-threshold-1.0 bypass was reproduced before the fix,
the fix was verified to both reject the bad configs and still gate a
max-risk call at the highest valid threshold, and it extends an
already-established range-guard principle rather than inventing one.
