# ADR 0115: The model writes prose; code keeps score

## Status
Accepted. Increment I3 of `IMPROVE_LOOP.md`; record in `IMPROVE_LOG.md`.
`reflection.impl: llm` is implemented, measured, and **off by default**.

## Context

ADR 0046 shipped the rule-based Critic and Judge and deferred the
LLM-backed pair to "a later slice, with the known bias mitigations". The
reason it stayed deferred was not design: no model was reachable without an
API key, and the repos this scaffold serves have none. ADR 0112 removed that
reason. The rubric scored dimension 3 at 3/10: interfaces raising
`NotImplementedError`.

## Decision

1. **The model writes prose; code computes every counted field.** The same
   rule as the summariser (ADR 0110). `LLMCritic.grounded_in` is
   `failure_signals(state)` — the citations the rule-based critic emits —
   never something the model claimed. `LLMJudge.score` is the rule-based
   weighted mean over per-term scores the model returned; a term the model
   omitted counts 0.0 (the anti-omission rule from ADR 0046, kept because a
   model that scores only the easy term must not lift the score by leaving
   the hard one out); values are clamped to [0, 1]; terms the model invented
   are dropped.
2. **Added, not substituted.** The critic's verbal feedback is the model's
   prose followed by the rule-based line, so the lesson stays traceable to
   its evidence. Same trade as ADR 0110, same reason.
3. **Bias controls are structural.** Evidence items are capped at
   `MAX_EXCERPT_CHARS` so bulk cannot read as quality. The judge asks twice
   with evidence in opposite orders and averages — a position-swap control
   for single-item grading — and reports `position_delta` in the rationale,
   so a judge that scores the same state differently by reading order is
   visible rather than averaged away silently. Two calls per judgment is
   the cost.
4. **Failure falls back, and says so.** A provider error or an unparseable
   reply falls back to the rule-based implementation with the reason in
   the output. Reflection must never take a run down (ADR 0110's
   telemetry rule).
5. **Reachable from `aef.yaml`.** `reflection: {impl: llm}` — refused at
   `agent_services` construction, not at the first reflect node, when no
   model provider exists. A block that validates while nothing can honour
   it is the ADR 0100 shape.
6. **Off by default.** On the eleven-scenario demo corpus the LLM judge
   and the rule-based judge both agree with the I1 ground truth 11/11, MAE
   0.0. The LLM judge costs ~10 s per judgment; the rule-based one is free.
   A knob that buys nothing measurable stays off — `knowledge_boost`'s
   rule.

## Evidence

Live, `impl: claude_code`, `claude-fable-5-1`, 2026-09-03: 11 states,
22 judge calls, agreement 11/11 for both judges, `position_delta` 0.0 on
every state, 0 fallbacks, mean 10.1 s per judgment, 118.6 s total. One
critic sample on `hard-both-5` cited `errors[0]` (computed) and wrote a
causal hypothesis the rule-based critic structurally cannot: "fixed
budget/threshold settings mismatched to task class". Seventeen fake-provider
tests pin the rules; four mutations (omission counted as 1.0, no clamping,
critic drops citations, no position swap) each failed tests.

## Consequences

- Rubric dimension 3: 3 → 7. Not higher: the corpus is too easy to show
  the LLM judge *beating* the rule-based one, and a control that has never
  seen a disagreement has not been exercised. The critic's causal prose is
  the visible gain, and nothing downstream reads it yet — that is I4's
  playbook.
- Every LLM reflection is `deterministic=False` by the reflect node's
  existing declaration; replay trusts the record.
- Self-preference bias (a judge preferring its own model's outputs) is not
  controlled here because nothing here compares model outputs; it becomes
  relevant when a judge ranks candidates, which is not this ADR.

## Confidence

High on the mechanism; the measurement shows parity, not superiority.

## Erratum (2026-09-03, ADR 0126)

**The cost of a judgment was reported in seconds and never in tokens, and
seconds understate it by a factor nobody had looked at.** Decision 6 rests on
"~10 s per judgment"; decision 3 spends two calls per judgment on the
position swap. What neither number captured is that `ClaudeCodeProvider` ran
inside the operator's own session: an adversarial round measured **211,470
input tokens per judge call** as issued — the operator's MCP tool schemas and
their `~/.claude/CLAUDE.md` re-sent every call — against 4,684 for the same
prompt with `--strict-mcp-config --mcp-config {}`. At list rates that is
$0.18 per call on cache reads and $2.22 uncached, doubled by the swap, on a
knob whose measured benefit was parity. The same inheritance is the likely
cause of a second observation in the A/B: the judge replied in the operator's
personal register. ADR 0126 adds the isolation flags; the per-call token cost
after them has NOT been re-measured live (the authoring session's quota was
exhausted) and is pending.

**`max_tokens` never reached the CLI.** `LLMJudge` sets `max_tokens=400` and
`ClaudeCodeProvider` drops it: the CLI has no output-length flag. The
"length controls" of decision 3 are the excerpt cap and the prompt, not a
provider-side cap. Documented in the provider's docstring rather than
silently implied.
