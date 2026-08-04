# Brainstorm: a real (not stubbed) Phase 3 reflection/critic-judge slice

Not a decision record — no code changes accompany this. Written per the
standing instruction to scope the next step toward self-improving loops
before touching Phase 3, after the kernel/state/security/eval/config/
providers/observability/cli audit pass concluded clean (docs accurate,
25 ADRs, 271 tests). Phase 4 evolution stays off the table regardless of
where this goes — this is exclusively about `aef/reasoning/reflection.py`
(`Critic`/`Judge`, currently pure `NotImplementedError` stubs) and how
their output would reach memory.

## What "real" means here, given this session's own standard

Every fix this session was verified by actually running real code against
a real local backend — no vendor mocking, no hypothetical reasoning from
source alone. A first Critic/Judge implementation should hold to that:
buildable and testable **without a live LLM call**, the same way
`aef/services/eval/rule_based.py`'s `RuleBasedEvaluator` is real and
tested without one. That points at a `RuleBasedCritic`/`RuleBasedJudge`
pair as the first real implementation, not an `LLMCritic` — grounded
strictly in signals already present on `AEFState` (`errors`,
`tool_results`, `scores`), which is also literally what `Critique.
grounded_in` and the module's own docstring already call for ("grounded
in external signals — tool errors, eval failures", not vibes). An
LLM-backed Critic is a legitimate later addition once this skeleton exists
and there's a `ModelProvider`-based node pattern to extend — starting
there first would repeat the mistake this session kept finding elsewhere
(a plausible-looking implementation nothing has actually exercised).

## The concrete gap found while scoping this

`aef.kernel.contracts.Services` has a DI slot for every other pluggable
backend — `model_provider`, `memory`, `graph_store`, `retriever`,
`evaluator`, `tracer`, `policy_engine`, `optimizer`, `durability` — but
**no `critic`/`judge` slot**. Constraint #2 (fixed node signature, DI-only
via `Services`, no globals) means a `Critic`/`Judge` can't be wired into a
real graph node at all until `Services` grows those two fields. This is
the literal first step, not an afterthought: add
`critic: Critic | None = None` and `judge: Judge | None = None` to
`Services`, mirroring how every other optional backend is already handled
(`None` = not configured, same pattern `require_model_provider()` follows
for the one slot that already has a "must be present" accessor).

## Proposed shape, smallest real slice

1. **`RuleBasedCritic`** (new, alongside `RuleBasedEvaluator`): scans
   `state.errors` and `state.tool_results` for failure signals (non-empty
   `errors`, a `tool_results` entry whose shape indicates failure — needs
   a real field-audit of what `tool_results` entries actually look like
   today before assuming a shape) and produces a `Critique` whose
   `verbal_feedback` is a templated, not generated, summary ("N tool
   call(s) failed: [...]"), with `grounded_in` populated from the actual
   error/tool-result identifiers that triggered it — not empty like
   `Critique.grounded_in`'s current default suggests it could ship.
2. **`RuleBasedJudge`**: scores `state.scores` against a caller-supplied
   rubric (`dict[str, float]` weights), producing a `Judgment` whose
   `rationale` is likewise templated from which rubric terms drove the
   score — deterministic, testable with hand-built `AEFState` fixtures the
   same way `test_rule_based.py` already does for `RuleBasedEvaluator`.
3. **A real `Node`**, e.g. `reflect_node`, calling both through `Services`
   and writing: `state.reflections` gets the verbal feedback appended
   (already a `list[str]` on `AEFState` — currently write-only, nothing
   populates it anywhere in the repo today, worth confirming with a quick
   grep before building on it), and `services.memory.write(MemoryRecord(
   kind="failure" | "success", ...))` per the CoALA taxonomy the memory
   module's own docstring commits to but nothing currently exercises for
   these two kinds specifically (existing tests cover "working"/"episodic"
   /"failure" generically, not from a reflection producer).
4. **Tests**: unit tests for both classes against hand-built adversarial
   `AEFState`s (empty errors, all-failing tool_results, an empty rubric,
   a rubric key missing from `state.scores`) — same adversarial-construction
   standard as ADR 0022/0023/0025, not just the happy path — plus one
   integration test chaining a real `GraphExecutor.run()` through
   `reflect_node` into a real `InMemoryMemoryStore` and asserting the
   record actually lands and is queryable back out.

## Explicitly deferred, not part of this slice

- **`Optimizer`** (`aef/services/optimizers/base.py`) — consumes
  `EvaluationRecord`s across a *batch* of runs; a single-run Critic/Judge
  slice doesn't need it and shouldn't reach for it prematurely.
- **LLM-backed Critic/Judge** — real second implementation once the
  rule-based one and its `Services`/`Node` wiring exist and are proven
  against a live graph run, not before.
- **Any promotion/gating logic** (which reflections get acted on, how a
  Judge's score feeds back into planning) — that's the self-improving-loop
  connective tissue the user's stated goal is ultimately about, but it's
  premature before a single real Critic/Judge pair exists to feed it.

## Field-audit already done: `tool_results` shape

Checked before writing this, not left as a guess: `AEFState.tool_results:
list[dict[str, Any]]` is untyped — no schema constrains what a node puts
in it. But there's already a de facto convention, not a blank slate:
`RuleBasedEvaluator` (`aef/services/eval/rule_based.py:66`) reads
`result.get("error")` truthiness to decide success/failure, and
`examples/hello_agent/graph.py`'s only real writer of this field
(`StateDelta(tool_results=[result])`) is consistent with that shape.
`RuleBasedCritic` should follow the same `.get("error")` convention rather
than inventing a second, competing one — two different "how do I tell if
a tool call failed" conventions across the codebase would be its own bug
in the making.
