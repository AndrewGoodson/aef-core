# ADR 0046: The reflection slice is rule-based, and its node is non-deterministic

## Status
Accepted. Implements M0 of the self-rewiring roadmap
(`docs/design/self-rewiring/03-roadmap.md` §M0).

## Context
`aef/reasoning/reflection.py` shipped `Critic`/`Judge` as pure
`NotImplementedError` stubs. Nothing in the repo wrote
`MemoryRecord(kind="failure"|"success")`, despite the memory module's
docstring committing to that CoALA taxonomy — so the "agents learn from
their runs" claim had no mechanism behind it.

Scoping the first real implementation surfaced a hard blocker.
`Services` (`aef/kernel/contracts.py`) had a DI slot for every pluggable
backend — `model_provider`, `memory`, `graph_store`, `retriever`,
`evaluator`, `tracer`, `policy_engine`, `optimizer`, `durability` — but
**none for `critic`/`judge`**. Constraint #2 (fixed node signature,
DI-only, no globals) meant a `Critic` could not be reached from any node at
all. The interfaces were structurally unwireable, not merely unimplemented.

Four design questions had no obvious default.

## Decision

**1. Rule-based first, not LLM-backed.** `RuleBasedCritic`/`RuleBasedJudge`
are grounded strictly in signals already on `AEFState` (`errors`,
`tool_results`, `scores`) — no model call, no clock read, no vendor SDK.
This mirrors `RuleBasedEvaluator`, which is real and tested without a live
LLM. `Critique.verbal_feedback` is templated, not generated, and every
claim carries a citation in `grounded_in` (`errors[0]`, `tool_results[2]`)
that resolves against the state it was given. An LLM-backed pair is a later
addition that changes no interface.

**2. One failure convention, not two.** `failure_signals(state)` is the
single answer to "what counts as a failure", reusing the
`result.get("error")` truthiness rule `RuleBasedEvaluator` already
established. `RuleBasedCritic` and `reflect_node` both call it rather than
each deciding independently.

**3. `reflect_node` declares `deterministic=False`.** Its *output* is a pure
function of state, so `True` looks defensible. It is wrong:
`ReplayEngine` **re-executes** nodes declared deterministic (`replay.py`),
and this node writes to the memory store — so `True` would append a
duplicate reflection on every replay. **A node whose output is
deterministic but which performs I/O must still declare
`deterministic=False`.** The node is `SideEffect.IO` with
`idempotency_key_fn = f"{run_id}:{node_id}:{checkpoint_seq}"` —
`checkpoint_seq` separates successive reflections within one run while
staying stable across a retry of the same step.

**4. Two anti-gaming choices in the Judge, made deliberately:**
- A rubric key **missing** from `state.scores` contributes `0.0` rather
  than being skipped. Skipping would let a candidate raise its score by
  not reporting a metric — reward hacking by omission. Scoring it zero
  means omission can never help.
- **Negative weights are rejected at construction**, because a negative
  weight inverts the rule above: omitting a "lower is better" metric would
  then *improve* the score.

An **empty rubric is also rejected at construction**. `Judgment.score` is
`float`, not `float | None`, so at scoring time a misconfigured rubric has
no honest return value — `0.0` would be indistinguishable from a genuine
zero. Same for non-finite weights and an all-zero rubric, which would
divide by zero and yield `nan` that `AEFState.scores` only rejects several
steps later (ADR 0022).

**5. The judgment is NOT written back into `state.scores`.** The Judge
*reads* `state.scores`; feeding its own output back would make a second
reflection step judge its previous judgement — a self-referential term no
rubric was written to weigh.

## Consequences
- `Services` grows `critic` / `judge` slots and `require_critic()` /
  `require_judge()`, following the existing `None`-means-unconfigured
  pattern. This adds a `kernel → reasoning` import edge; `reflection.py`
  imports only `aef.state`, so there is no cycle (verified in both import
  orders).
- Reflection is now **partially real**, not stubbed. `docs/roadmap.md`,
  `README.md`, `CLAUDE.md`, and `AGENTS.md` are updated; claiming otherwise
  would be the "docs describe something that doesn't exist" failure this
  repo keeps auditing for.
- The M0 acceptance property holds: a real `GraphExecutor` run produces
  failure/success records queryable via `MemoryStore.query()`. 49 tests,
  including the replay test that pins decision 3 — replaying a trace does
  **not** append a second memory record.
- Excerpts are bounded (`MAX_EXCERPT_CHARS`, `MAX_QUOTED_SIGNALS`).
  Reflections land in state *and* memory, both read back into a context
  window later; an unbounded error string would silently consume the
  context budget several steps downstream.
- **Not wired into `aef.yaml` config.** M0's scope is the mechanism;
  callers construct `Services(critic=..., judge=...)` directly. Config
  wiring is a follow-up, not a gap in this slice.

## Alternatives Considered
- **LLM-backed Critic first.** Rejected: it would ship a plausible-looking
  implementation nothing had actually run, which is the exact failure mode
  this repo's adversarial-construction standard exists to prevent. It also
  cannot be tested against hand-built adversarial state.
- **`deterministic=True` with the memory write hoisted out of the node.**
  Rejected: it splits one logical step across two nodes purely to satisfy a
  declaration, and the second node still has the same problem.
- **Skip missing rubric keys instead of scoring them 0.0.** Rejected on
  anti-gaming grounds — see decision 4. Worth restating because it is
  *locally* the friendlier behaviour and will look like a bug to someone
  who has not read this ADR.
- **Return `Judgment(score=0.0)` for an empty rubric instead of raising.**
  Rejected: indistinguishable from a real zero, and the caller has no way
  to tell. Same reasoning as `RuleBasedEvaluator.cost_dollars` staying
  `None` rather than fabricating a figure.

## Confidence
High on the mechanism and on decision 3 — the replay property is directly
tested, not argued. Medium on the Judge's weighting scheme: a weighted mean
is the obvious first choice, but nothing yet validates that it correlates
with anything a downstream proposer would want to optimise. That validation
needs the eval corpus (M2/M5), which does not exist. Explicitly **not**
claimed: that these reflections are good enough to ground a proposer — M8
must re-check that against a real corpus, not assume it.
