# ADR 0012: `PolicyEngine` must reject a `ToolCall.tool_name` that doesn't match the `Tool` it's evaluated against

## Status
Accepted

## Context
Continuing the same audit that found `idempotency_key_fn` (ADR 0010) and
the inert `Edge` flags (ADR 0011) — grep every declared field for a real
read, not just a write — turned up `ToolCall.tool_name`. It's set at every
call site (`ToolCall(tool_name=..., ...)`) but never read anywhere:
`PolicyEngine._decide` and the audit log both key off `tool.name` (the
`Tool` object's own attribute), never `call.tool_name`.

This is more than dead code. `PolicyEngine.evaluate(tool, call)` takes the
`Tool` object and the `ToolCall` as two separate arguments, and nothing
ever checked they agree on which tool is actually being evaluated. In a
system whose own stated threat model is "assume prompt injection will
sometimes succeed... design for containment, not detection"
(`aef/security/tool.py`'s module docstring), a caller that resolves a
`Tool` object one way and constructs a `ToolCall` another way — a lookup
bug, or an LLM-controlled value influencing which branch built the
`ToolCall` — could have policy evaluated against the wrong tool's identity
entirely: correct scopes checked, but for a tool that isn't the one about
to run.

## Decision
`PolicyEngine._decide` now checks `call.tool_name != tool.name` first,
before the forbidden-name check or any scope logic, and denies on
mismatch with a reason string naming both the declared and actual tool
names. This is deliberately the very first check — a name mismatch means
nothing else about the call's evaluated properties (scopes, risk) can be
trusted to describe the tool that will actually execute, so there's no
value in also computing those checks.

Existing call sites (`examples/hello_agent`, all of `tests/security/test_tool.py`)
already passed matching names — this fix changes behavior only for the
mismatch case, which no test previously exercised.

## Consequences
- Any caller constructing `ToolCall(tool_name=..., ...)` inconsistently
  with the `Tool` object passed to `PolicyEngine.evaluate()` now gets a
  clear `DENY` with an explanatory reason, instead of policy being
  silently evaluated as if the mismatch didn't exist.
- The correct, and now enforced, pattern is `ToolCall(tool_name=tool.name, ...)`
  — establishing `tool.name` as the single source of truth and `call.tool_name`
  as the caller's *claim*, checked against it.

## Alternatives Considered
- **Drop `ToolCall.tool_name` entirely and derive it from `tool.name` inside
  `evaluate()`.** Rejected: `ToolCall` is meant to represent what was
  *requested* (e.g., what an LLM's tool-call output actually named),
  independent of how the caller resolved that name to a `Tool` object —
  collapsing them loses the ability to detect exactly the mismatch this
  ADR is about.
- **Log the mismatch but still evaluate against `tool`'s real
  scopes/name.** Rejected: silently proceeding on a detected
  inconsistency contradicts the module's own deny-by-default philosophy;
  a mismatch is itself sufficient reason to deny, not a warning-worthy footnote.

## Confidence
High — directly analogous to ADR 0010/0011's pattern (declared field,
zero consumers, a concrete plausible failure mode once you ask "what if
these two arguments disagree"), and the fix is small, tested, and doesn't
change behavior for any correctly-constructed call.
