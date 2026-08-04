# Architecture & Bug-Hunt Review — 2026-08-04

Read-only review pass (Fable 5). No code changed; this file is the only
artifact. Scope: green-state attestation, external-standards benchmark
(2026), and an adversarial bug hunt in the *seams between components* that
the ADR 0022–0030 single-module audits structurally could not reach.
`aef/evolution/` deliberately out of scope (gated per ADR 0006/0010).

Baseline at review: HEAD `f468b68`, 30 ADRs, clean tree.

---

## 1. Green-state attestation

Actual command output on this checkout:

```
pytest -q            -> 288 passed, 50 warnings
mypy --strict aef    -> Success: no issues found in 61 source files
ruff check .         -> All checks passed!
ruff format --check aef tests -> 90 files already formatted
```

All green, matching the stated baseline exactly.

### CI parity

`.github/workflows/ci.yml` runs, on Python 3.11 and 3.13: `ruff check aef
tests`, `ruff format --check aef tests`, `mypy aef` (strict via
`[tool.mypy] strict = true` in `pyproject.toml`, so equivalent to the
local `mypy --strict aef`), `pytest tests/test_vendor_isolation.py`,
`pytest tests/test_schema_compat.py`, and the full `pytest -q`. Every
local gate is represented in CI. Both CI-referenced test files exist.

Two **directional** differences, neither a green-local/red-CI risk:

- Local `ruff check .` covers the whole repo; CI checks only `aef tests`.
  So a lint error under `examples/` would pass CI but fail locally — CI is
  *weaker*, not a hidden-red risk. (`examples/` is currently clean under
  both ruff and `mypy --strict`.)
- CI type-checks only `aef`, not `examples/` or `tests/`. Same direction:
  a regression there fails locally before CI. Very low severity; noted for
  completeness, not flagged as a finding.

**Attestation: green, and nothing green locally can be red in CI.**

---

## 2. Standards benchmark (2026)

Each area marked **CONFORM** / **DEVIATE (documented)** / **DRIFT**, with
the specific source checked.

### (a) Anthropic agent-architecture guidance — CONFORM (mildly conservative)
- *Building Effective Agents*, *Effective Context Engineering*, *Writing
  Tools for Agents*, *Multi-Agent Research System*, Agent SDK / Skills / MCP
  posts (anthropic.com/engineering, claude.com/blog).
- The two-plane design (deterministic control plane, quarantined LLM nodes)
  is squarely Anthropic's *workflow* side of the workflow-vs-agent line, and
  the current context-engineering post explicitly frames the deterministic
  harness around the model as the engineering surface — i.e. the industry is
  moving *toward* deterministic scaffolding, not away. Single-agent default
  with multi-agent deferred matches the multi-agent post's own "only when
  breadth-first parallelizable; ~15× the tokens" caution.
- One honest tension: Anthropic's frontier *multi-agent* practice favors
  giving the model dynamic orchestration control (subagents spawning
  subagents), which aef-core's static-graph bias is deliberately more
  conservative than. Defensible (reliability/auditability trade), and the
  fixed topology is a written design premise, not accidental.
- The one warning to keep re-checking: Anthropic cautions that frameworks
  "add layers of abstraction that obscure debugging." aef-core *is* a
  framework-shaped scaffold — justified because replay/checkpoint/DI are the
  entire point, but this is worth periodic re-justification, not a one-time
  pass.

### (b) Graph-execution engineering — CONFORM (two gaps → Findings 1, 2)
- LangGraph (Pregel/BSP; `recursion_limit`, `interrupt()`, pending-writes),
  Temporal (durable execution, at-least-once activities, idempotency keys),
  BSP/Pregel (superstep barrier). Sources: docs.temporal.io/activity-
  definition, LangGraph GRAPH_RECURSION_LIMIT + fault-tolerance docs,
  pk.org/Pregel notes, Diagrid & zalt.me checkpoint analyses.
- `deterministic=True` re-execute / `deterministic=False` trust-recorded is
  *exactly* Temporal's workflow-replay model. The checkpoint-after-superstep
  + cursor + node-owned idempotency-key requirement matches Temporal/
  LangGraph norms; at-least-once on the in-flight node is the universally
  accepted semantics, not a flaw.
- `max_steps=1000` single counter matches LangGraph's `recursion_limit`
  (default 25) — a flat superstep cap is standard. Minor ergonomic gap: it's
  executor-construction-level, where LangGraph's is per-invocation config.
  Peers at this maturity add per-node timeout + retry budget next; noted as
  a roadmap direction, not a finding.
- Fan-out declared-but-deferred (ADR 0007) is reasonable staging — sequential
  is a degenerate BSP (barrier semantics hold at width 1). **Caveat that
  matters:** executing fan-out later forces a checkpoint-schema change
  (multiple pending cursors + pending-writes-style partial-superstep
  persistence). Deferring is safe *only if the checkpoint format is versioned
  now* — worth confirming before fan-out lands.
- Two real gaps surfaced here → Findings 1 (non-atomic writes) and 2 (HITL/
  resume + idempotency-key not enforced on resume).

### (c) Self-improving loops — CONFORM
- Reflexion, GEPA (ICLR 2026 oral), DSPy, LLM-as-judge bias literature
  (position/verbosity/self-preference), Hamel Husain judge guide, DeepEval/
  Arize 2026. Sources: arxiv 2507.19457, hamel.dev, deepeval.com, arize.com.
- `docs/design/phase3-reflection-critic-judge-brainstorm.md`'s rule-based-
  first slice matches 2026 practice precisely: "if a failure can be verified
  with code, always use a code-based eval" — grounded in already-recorded
  signals (tool errors, eval failures), deterministic, replayable (fits the
  `deterministic=True` contract), no bias mitigation needed. The brainstorm's
  own honesty about an LLM-reflection second slice is the right framing: a
  rule-based critic can't diagnose *why* a trajectory failed semantically
  (GEPA's gains come from NL reflection), so the ceiling is low — fine as a
  first step, not as a stopping point.

### (d) OTel GenAI semconv — mostly CONFORM, one DRIFT (→ Finding 3, Low)
- GenAI semconv is still **not stable** as of 2026 (moved to a dedicated
  repo, no tagged release). Sources: opentelemetry.io/docs/specs/semconv
  registry, John Hodge status post, OTel 2026 GenAI-observability blog.
- The two attributes aef-core actually *emits* — `gen_ai.usage.output_tokens`
  and `gen_ai.response.model` — are both spec-current. Pinning local
  constants (ADR 0008) rather than importing the incubating package remains
  defensible given the repo churn.
- **One drift:** `gen_ai.system` was renamed to `gen_ai.provider.name` in
  semconv v1.37.0 (Aug 2025). `semconv.py` still defines `GEN_AI_SYSTEM =
  "gen_ai.system"`. Low severity — it's a defined-but-*unused* constant (no
  emitted span references it), so no telemetry is currently wrong; it would
  only mislead a future author who reaches for it.

---

## 3. Findings (ranked by severity)

### Finding 1 — Checkpoint/cursor writes are non-atomic; a torn write bricks resume with no fallback to the last good checkpoint. **HIGH.**
ADR 0026 hardened the *read* side (a corrupt checkpoint raises a named
`CorruptedCheckpointError` instead of a bare `JSONDecodeError`). The *write*
side was never hardened, and `load_latest` has no recovery path.

- **Reproduction (run, confirmed):** write good checkpoints seq 0 and 1 via
  `FileDurabilityBackend.save_checkpoint`, then simulate a crash mid-write of
  seq 2 by leaving a truncated `2.json` (`'{"run_id": "r1", "agent_id"'`).
  `list_checkpoints('r1')` → `[0, 1, 2]`; `load_latest('r1')` picks
  `max()` = 2 and raises `CorruptedCheckpointError`.
- **Expected:** resume recovers from seq 1 (intact on disk), or the torn
  file never exists because writes are atomic.
- **Actual:** `load_latest` raises; `resume()` is permanently bricked for
  that run despite two intact checkpoints sitting right there.
- **Worst case (per external research, not separately reproduced here):**
  `cursor.json` is *overwritten in place* every super-step via `write_text`
  — a torn write there corrupts the resume pointer itself, not just one
  checkpoint. Confidence that the cursor write is equally non-atomic: **High**
  (same `write_text` call, read in source); confidence a real crash lands
  mid-write: inherent to non-atomic I/O.
- **Confidence: High.** Standard fix is well-established: write to a temp
  file in the same directory, `fsync`, `os.replace()` (atomic on POSIX
  same-filesystem), and consider `load_latest` falling back to the highest
  *loadable* checkpoint. **Needs an ADR** (it changes durability's
  write-path contract and the load_latest recovery semantics).

### Finding 2 — HITL approval is checked *after* the preceding node runs, so a gated resume re-executes that node — and a gate before the first checkpoint makes the run unresumable. **MEDIUM-HIGH.**
`GraphExecutor._resolve_route` raises `HumanApprovalRequiredError` *after*
`node.fn` already executed (the node produces the state a human reviews),
and the raise happens *before* `save_checkpoint`/`save_cursor` for that step.

- **Reproduction A (run, confirmed):** graph `A -[HITL]-> B`, gate on the
  entry node's outgoing edge. First `run()` (no approval) blocks; node A's
  side effect fired once; **no checkpoint was ever saved.** Operator grants
  approval and calls `resume('run-hitl')` → `GraphExecutionError: no
  checkpoints found ... nothing to resume`. The paused run is unrecoverable;
  only a full re-`run()` continues it (re-firing A).
- **Reproduction B (run, confirmed):** graph `A -> B -[HITL]-> C`, gate on
  B's outgoing edge, B has a side effect. `run()` blocks at the gate with B's
  side-effect count = 1, checkpoint `[1]` (from A) on disk, cursor = `B`.
  `resume()` with approval completes with B's side-effect count = **2** — B
  re-ran on resume.
- **Expected:** the human gate pauses *before* the consequential node's side
  effect, and resume continues without re-executing it.
- **Actual:** the node immediately before the gate always re-runs on resume;
  if that gate precedes any checkpoint, the run can't be resumed at all.
- **Context / how bad:** external research confirms LangGraph's `interrupt()`
  *also* re-executes pre-interrupt code, so the re-exec itself is an accepted
  pattern **provided idempotency covers it.** But aef-core's kernel never
  *consults* the `idempotency_key` on resume — it only requires the
  `idempotency_key_fn` to *exist* (ADR 0010, by design: "the kernel does NOT
  enforce idempotency"). So the sole mitigation for double-execution is
  entirely node-author-dependent, and the "unresumable before first
  checkpoint" case is strictly worse than LangGraph, which always
  checkpoints. See Finding 5.
- **Confidence: Medium-High** that this is a real design gap (both behaviors
  reproduced); **Medium** that it warrants changing (the re-exec matches peer
  behavior; the unrecoverable-run case is the part most worth fixing —
  checkpoint before raising the HITL error, so a paused run is always
  resumable). **Needs an ADR** if the gate/checkpoint ordering changes.

### Finding 3 — `semconv.GEN_AI_SYSTEM` is a stale constant (`gen_ai.system` → `gen_ai.provider.name`, v1.37.0). **LOW.**
- **Reproduction (read, confirmed):** `semconv.py:14` defines `GEN_AI_SYSTEM
  = "gen_ai.system"`; grep shows only `GEN_AI_USAGE_OUTPUT_TOKENS` and
  `GEN_AI_RESPONSE_MODEL` are emitted anywhere — `GEN_AI_SYSTEM` (and
  `GEN_AI_REQUEST_MODEL`, `GEN_AI_USAGE_INPUT_TOKENS`, `GEN_AI_OPERATION_NAME`)
  are defined-but-unused.
- **Expected:** the constant reflects the current spec name, or is removed.
- **Actual:** stale name, but inert (no span emits it) — no telemetry is
  wrong today; risk is only that a future author emits it under the old name.
- **Confidence: High** on the rename fact (v1.37.0, Aug 2025) and on the
  dead-constant status; **Low** severity. Would not need an ADR (ADR 0008
  already covers "update deliberately when the spec moves" — this is that
  update); a one-line commit renaming/removing suffices.

### Finding 4 — Config accepts semantically-empty/degenerate values that pydantic can't catch. **LOW.**
- **Reproduction (run, confirmed):** `ModelProviderConfig(impl="anthropic",
  fallback=["anthropic"])` builds a `FallbackProvider` whose "fallback" is
  the *same vendor* as primary — on a real vendor outage it fails
  identically, defeating the point. `fallback=["anthropic","anthropic",
  "anthropic"]` is likewise accepted. `AgentConfig(..., objectives="")` is
  valid — the agent's whole stated purpose can be blank.
- **Expected (arguable):** a warning or rejection for a fallback duplicating
  the primary impl, and a non-empty `objectives`.
- **Actual:** all silently valid.
- **Confidence: High** these are unvalidated; **Low** severity — none crash,
  and "same-vendor fallback" is a judgment call (a user might deliberately
  want two anthropic endpoints). Best handled as a `doctor`-level advisory
  warning rather than a hard schema rejection. No ADR needed.

### Finding 5 — (Informational, by design) idempotency key is declared but never enforced on resume.
Not a bug — ADR 0010 explicitly makes the kernel compute-and-expose the key,
not enforce it. Flagged here only because it is the *load-bearing mitigation*
for Finding 2's double-execution, and that mitigation is 100%
node-author-dependent with no kernel backstop or dedupe ledger. External
research independently raised the same point ("declaration without
enforcement"). Worth a doc cross-reference from any HITL/resume fix, not a
code change on its own.

### Seams that came back CLEAN (checked, nothing found)
- **`StateDelta.apply()` `model_copy` validator bypass (the ADR 0022
  gotcha):** every value in the `update={...}` dict is either a
  pre-validated `StateDelta` field or a merge/concat of already-validated
  state — no path feeds a *new* unvalidated value (e.g. non-finite score,
  non-positive `context_budget_tokens`) through the bypass. The only
  computed value is `checkpoint_seq + 1`, which has no constraint. Clean.
- **Cursor pointing at a node deleted in a later graph version:** `resume()`
  → `_run_from` → `self._graph.nodes.get(cursor)` → `None` →
  `GraphExecutionError: no such node 'X'`. Clear, correct error.
- **Replay against a graph whose node *versions* changed:** a
  `deterministic=True` node whose logic changed raises
  `DeterminismViolationError` on replay (recorded output ≠ recomputed) —
  arguably-correct (the old run genuinely isn't reproducible by new code),
  already covered by the ADR 0023 test surface.

---

## 4. Recommended next actions (ordered; each scoped for one commit)

1. **Atomic durability writes (Finding 1)** — `save_checkpoint` and
   `save_cursor` write to a temp file in the same dir, `fsync`,
   `os.replace()`. Add a test: a truncated `N.json` no longer bricks
   `load_latest` (either because it can't exist, or because `load_latest`
   falls back to the highest loadable seq). Write an ADR. *Highest value:
   directly closes the one High finding and completes ADR 0026's story.*
2. **Make HITL pauses always resumable (Finding 2, the recoverable half)** —
   checkpoint (and save a cursor at the gate) *before* raising
   `HumanApprovalRequiredError`, so a run gated before its first checkpoint
   can still be resumed. Decide separately whether to also move the approval
   check to node-*entry* to avoid re-executing the preceding node; ADR either
   way.
3. **Rename/remove the stale `GEN_AI_SYSTEM` constant (Finding 3)** —
   `gen_ai.system` → `gen_ai.provider.name`, or delete the unused GenAI
   constants and keep only the two that are emitted. One-line-ish; no ADR.
4. **`aef doctor` advisories for degenerate config (Finding 4)** — warn on a
   fallback impl equal to (or duplicated within) the primary, and on empty
   `objectives`. Advisory, not a hard schema failure.
5. **Version the checkpoint format now, before fan-out (Phase 2 prep)** — per
   the graph-standards benchmark, executing fan-out later forces a
   checkpoint-schema change (multiple pending cursors / pending-writes).
   Confirm the on-disk format carries a version field so that change is
   additive, not breaking. Investigation + possibly a small schema note.

---

## 5. Explicitly out of scope

- **`aef/evolution/`** — gated by ADR 0006/0010; reviewing or recommending
  changes to it is out of bounds by standing instruction.
- **Re-auditing ADR 0022–0030 fixes** — this pass deliberately hunted the
  *seams between* components, not the modules those ADRs already hardened.
- **Live/paid backends** — no real Anthropic or hosted-mem0 calls were made;
  the mem0 integration was reviewed via its existing local-backend tests and
  source, not a new live run.
- **Performance / load** — no benchmarking; findings are correctness- and
  crash-recovery-focused.
- **Phase 2/3 stub *implementations*** (kg / context / optimizers / planner /
  reflection) — confirmed still `NotImplementedError` stubs in prior passes;
  their *interfaces* were benchmarked (§2c) but not re-audited for bugs, as
  there's no executable body to break.

---

*Review method: green-state attestation by running the real gates;
standards benchmark via 2026 web sources (cited inline); bug hunt by
hand-constructing adversarial inputs and running real code against them
(the technique that produced ADRs 0022–0030). Findings 1, 2, and 4 were
reproduced by executing real objects/functions; Finding 3 by reading
source + grep. No repository code was modified.*
