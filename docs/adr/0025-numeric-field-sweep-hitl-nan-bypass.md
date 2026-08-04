# ADR 0025: Numeric-field adversarial sweep — `ToolCall.risk` NaN bypassed the HITL gate

## Status
Accepted

## Context
Following the pattern that found ADR 0022 (a `float("inf")`/`nan` sweep
across `scores`), swept every float/int field across the codebase lacking
a range or finiteness check, and decided case by case whether it was a
real risk or genuinely fine unconstrained: `ToolCall.risk`,
`PolicyConfig.require_hitl_above_risk`, `aef.config.schema.PoliciesConfig.
require_hitl_above_risk`, `Provenance.token_cost`, and
`AEFState`/`StateDelta.context_budget_tokens`.

**The critical finding**, reproduced directly before writing any fix:
`aef/security/tool.py`'s `PolicyEngine._decide()` gates every tool call on
`call.risk > self._config.require_hitl_above_risk`. `ToolCall` is a plain
`@dataclass(frozen=True)` with no construction-time validation at all —
nothing stopped `risk=float("nan")`. In Python, any comparison against
`NaN` (`nan > x`, for any `x`) evaluates to `False`. A `ToolCall` built
with `risk=nan` therefore never satisfies `risk > threshold`, so
`PolicyEngine.evaluate()` returns `ALLOW` unconditionally instead of
`REQUIRE_HITL` — silently defeating the exact mechanism this module's own
docstring names as the security-critical containment layer ("any call
whose risk exceeds the configured threshold requires explicit
human-in-the-loop approval rather than executing"). Confirmed live: a
`ToolCall(risk=float("nan"))` evaluated against a `PolicyConfig` configured
with `require_hitl_above_risk=0.5` returned `PolicyDecision.ALLOW`. The
same bypass exists symmetrically from the threshold side — a NaN
`require_hitl_above_risk` disables the gate for every call regardless of
risk.

This is more severe than ADR 0022's finding: that bug silently corrupted
an evaluation metric; this one silently disables the human-approval gate
that stands between a tool call and execution, in a module whose entire
stated threat model is "assume prompt injection will sometimes succeed and
contain it" — a risk value reaching `ToolCall` isn't necessarily
attacker-controlled today (nothing yet computes risk from LLM output), but
the gate exists specifically for the case where an upstream risk-scoring
step is wrong, compromised, or itself downstream of adversarial input, and
a construction-time hole in that gate undermines the guarantee regardless
of how the bad value gets there.

The other fields swept were lower-severity, real-but-not-security findings
in the same spirit as ADR 0022: `Provenance.token_cost` (summed for cost/
eval metrics in `aef/kernel/executor.py` and
`aef/services/eval/rule_based.py` — a negative value would silently
understate an aggregate) and `context_budget_tokens` (a zero or negative
"budget" is semantically nonsensical, and no current consumer would catch
it since the Phase 2 `Retriever` that would divide work by this value
isn't wired yet — better to reject at the source than let it reach a
future consumer unconstrained). `GraphStore.Entity`/`Relation.valid_from/
valid_until` and `MemoryRecord.valid_from/valid_until` were checked too
and are fine unconstrained: they're plain optional timestamps for a
not-yet-implemented Phase 2 temporal store (ADR 0003/0004), not values fed
into any live comparison today.

## Decision
- `ToolCall.__post_init__` now rejects non-finite `risk` and any `risk`
  outside `0.0..1.0` (the range its own docstring already documented).
- `PolicyConfig.__post_init__` (the runtime dataclass `PolicyEngine`
  actually compares against) now rejects a non-finite
  `require_hitl_above_risk`.
- `aef.config.schema.PoliciesConfig.require_hitl_above_risk` gained the
  same finiteness guard at the pydantic-config-load layer — defense in
  depth for the day this value is wired into the runtime `PolicyConfig`
  (currently partial per ADR 0014), so a bad value in `aef.yaml` fails at
  `aef doctor`/config-load time, not silently at the security gate.
- `Provenance.token_cost` gained `Field(ge=0)`.
- `AEFState.context_budget_tokens` gained `Field(gt=0)`;
  `StateDelta.context_budget_tokens` (the `int | None` override) gained
  the same `gt=0` constraint, applying only when the override is set.

## Consequences
- The HITL bypass is now unreachable: `ToolCall` and `PolicyConfig` cannot
  be constructed with a NaN/infinite risk value in the first place, so
  `PolicyEngine._decide()`'s `>` comparison can never silently short-circuit.
- All existing call sites already passed values within the new bounds
  (grepped every `ToolCall(...)`/`risk=`/`token_cost=`/
  `context_budget_tokens=` construction in `aef/`, `tests/`, and
  `examples/`) — full suite green (271/271, up from 263/263) with zero
  call sites needing updates; this is a pure tightening.
- New adversarial tests cover all five fields, including one confirming
  `PolicyEngine.evaluate()` denies-by-construction rather than merely
  documenting the old exploit shape (the `ToolCall(risk=nan)` call itself
  now raises before a `PolicyEngine` could ever see it).

## Alternatives Considered
- **Clamp risk to `[0, 1]` instead of rejecting out-of-range values.**
  Rejected, same reasoning as ADR 0022: a silently clamped risk value
  (e.g. an upstream bug producing `risk=50.0` silently becoming `1.0`) is
  a plausible-but-wrong number a security gate could act on incorrectly
  with no error — worse than a loud rejection at construction.
- **Only fix `ToolCall.risk`, not `PolicyConfig.require_hitl_above_risk`.**
  Rejected: the bypass is symmetric (either side of the `>` being NaN
  produces the same silent-ALLOW outcome), so fixing only one side leaves
  the other half of the same vulnerability open.

## Confidence
High for the `ToolCall`/`PolicyConfig` fix — the exact exploit (`NaN`
risk producing `ALLOW` from a real `PolicyEngine.evaluate()` call against
a real HITL-configured threshold) was reproduced before any fix existed,
and the fix was verified to close it by construction, not just add a
downstream check. High for `token_cost`/`context_budget_tokens` as
tightenings consistent with ADR 0022's established rationale, though
these are lower-stakes since no current code path has yet been shown to
misbehave on a negative/zero value (the risk is a future one, not a
reproduced live bug like the other two findings in this session).
