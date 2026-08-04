# Self-rewiring agents — 00: current state (ground truth)

**Status:** planning artifact. No code changes accompany this document.
**Method:** every claim below was read out of the source and is cited
`file:line`. Where something does not exist, that is stated as an absence,
not inferred. Baseline at time of writing: 321 tests passing, `mypy
--strict` clean, ruff clean, HEAD `045337d`.

This is Phase 1 of the self-rewiring planning program: *what already exists
that such a system would plug into, and what does not exist at all.*

---

## 1. What "self-rewiring" must operate on

**The Graph.** `Graph` is a frozen dataclass — `id`, `version` (semver,
per-subgraph), `nodes: Mapping[str, Node]`, `edges: Sequence[Edge]`,
`entry_node` (`aef/kernel/graph.py:32-38`), frozen into
`MappingProxyType`/`tuple` at construction (`graph.py:40-42`).

**`Node`** (`aef/kernel/contracts.py:192-210`): `id`, `version`, `fn:
NodeFn`, `deterministic: bool` required; `side_effects=PURE`,
`cost_model`, `idempotency_key_fn=None`, `telemetry_tags=()`,
`fallback_node_id=None` defaulted. `NodeContractError` is raised iff
`side_effects != PURE` and no `idempotency_key_fn` (`contracts.py:204-210`).

**`Edge`** (`contracts.py:220-269`, `frozen=True, eq=False`): `from_node`,
`to_node: str | tuple[str, ...]`, `condition=_always`, `priority=0`,
`requires_human_approval=False`, `requires_deterministic_fallback=False`.
Equality compares all six fields, with `condition` compared by
`__code__` (`_condition_key()`, `contracts.py:235-245`) — so a rebuilt,
structurally identical lambda compares equal (ADR 0020), but two
behaviourally identical conditions written differently compare unequal, and
**closure-captured values are not compared** (same `__code__`, different
closure ⇒ falsely equal).

### 1.1 The blocker that shapes everything: a Graph is not serializable

`Node.fn` and `Edge.condition` are Python callables. There is no
`to_dict`/`from_dict`/`model_dump` on `Graph`, `Node`, or `Edge` anywhere
in the kernel (verified by grep). The only way a graph comes into existence
today is imperatively: `aef run` imports a module and calls its
`build_graph()` function (`aef/cli/run.py:67-70, 83`). **No declarative
graph specification, and no loader for one, exists.**

Consequences, all of which the architecture must answer:

- A proposing agent cannot emit "a new Graph" as data.
- An archive cannot store a graph version as data.
- A wiring diff cannot be persisted or rendered for review as data.

This single fact is why the design cannot simply "have the agent write a
new Graph object", and it is addressed in `01-architecture.md`.

---

## 2. Diffing: what `Graph.diff()` can and cannot express

`Graph.diff(other)` (`graph.py:76-92`) returns `GraphDiff`
(`graph.py:127-143`): `nodes_added`, `nodes_removed`, `nodes_changed`
(frozensets of ids), `edges_added`, `edges_removed` (tuples of `Edge`),
plus `is_empty` (`graph.py:135-143`).

**Detects:** node add/remove; a node whose `version` string changed
(`graph.py:82-84`); any edge whose `from_node`, `to_node`, `condition`
(`__code__`), `priority`, `requires_human_approval`, or
`requires_deterministic_fallback` differs — surfacing as one removed + one
added `Edge` (`graph.py:85, 90-91`).

**Misses:**
- A node whose `fn`, `deterministic`, `side_effects`, or
  `fallback_node_id` changed **without a version bump** — node change is
  detected *only* by version-string inequality (`graph.py:82-84`).
- **Edge declaration-order changes.** Edges are compared as a `set`
  (`graph.py:85`), but declaration order is the documented tie-break for
  equal-priority edges (`edges_from`, `graph.py:63-70`) — so a reorder is a
  real behavioural change that `diff()` reports as empty.
- Which-edge-changed pairing: there is no "modified" concept, no linkage
  between a removed and an added `Edge`.
- `Graph.id`, `Graph.version`, and `entry_node` changes — never compared.
- Duplicate-edge multiplicity (the set collapses duplicates).

**And it is not persistable:** `edges_added`/`edges_removed` hold `Edge`
objects containing callables.

**Verdict for the design:** `GraphDiff` is a useful *in-memory* comparison
of two live graphs, but it is **not** a sufficient wiring-diff currency for
a propose→review→archive pipeline. See ADR on wiring-diff representation.

---

## 3. Replay: what it validates, and the gate correction it forces

`ReplayEngine.replay(trace)` (`aef/kernel/replay.py:40-78`): rejects an
empty trace (`:41-42`); runs `_validate_chain` (`:43`); then per record
looks up the node **by id in the engine's own graph** (`:47`) — a missing
node raises `DeterminismViolationError` (`:48-51`). If `node.deterministic
and not record.is_fallback` (`:52`) it re-executes `node.fn(...)` and
raises on a `StateDelta` or `Route` mismatch (`:58-72`). Otherwise the
recorded delta is trusted verbatim (ADRs 0036/0039). State is rebuilt via
`record.delta.apply(record.input_state)` (`:75`).

`_validate_chain` (`:80-110`) checks the trace's **internal** consistency
only: no fan-out route, `END` only on the final record, and
`record[i].route == record[i+1].node_id`.

### 3.1 Replay cannot detect a wiring regression

Edges, conditions, and priorities are **never consulted** by replay. Replay
follows the *recorded* path; it does not re-resolve routing against the
graph it was constructed with. Therefore:

> A graph whose wiring has been changed will happily replay an old trace,
> because replay never asks the new graph where it would have gone.

Replay detects **node-implementation** regressions (a deterministic node
whose output changed), not **wiring** regressions. It also aborts at the
first mismatch rather than producing a report.

**This is a correction to the program's stated Gate 2.** "Replay the golden
corpus" is necessary but insufficient; the wiring gate must
**re-execute** each golden scenario from its recorded initial state through
the *candidate* graph and compare the resulting trace and final state
against the golden record. Both mechanisms are needed and they check
different things — specified in `gates/`.

Secondary fact: `record.context.graph_version` carries the recording
graph's version (`aef/kernel/executor.py:122`) but replay never checks it —
there is no version-mismatch guard.

---

## 4. Traces: nearly persistable, not yet

`NodeExecutionRecord` (`aef/kernel/executor.py:45-60`): `node_id`,
`input_state: AEFState`, `context: Context`, `delta: StateDelta`, `route:
Route`, `is_fallback: bool = False`. `ExecutionResult` (`:63-66`) carries
`final_state` and an optional `trace`. `run(record_trace=True)` appends one
record per super-step (`:133-143`).

- `AEFState` and `StateDelta` are pydantic and round-trip JSON
  (`aef/state/schema.py:50`, `aef/state/delta.py:21`; proven by durability's
  `model_dump_json` + `load_state`, `aef/kernel/durability.py:116, 123`).
- **Not round-trippable today:** `Context` is a plain frozen dataclass with
  no serializer (`contracts.py:104-131`); `Route`'s `END` is a singleton
  sentinel object with no JSON form (`contracts.py:159-174`).
- There is **no trace (de)serializer anywhere** in the kernel.

**Verdict:** a golden-trace/scenario corpus is achievable but requires a
small, explicit trace serializer (Context, the `END` sentinel, and the
record envelope). That is a named milestone, not a footnote.

---

## 5. Durability: no graph or wiring artifact store exists

`DurabilityBackend` (`durability.py:72-102`) persists `AEFState`
checkpoints and a cursor only: `save_checkpoint`, `load_latest`,
`load_checkpoint`, `list_checkpoints`, `save_cursor`, `load_cursor`.
`FileDurabilityBackend` lays out `root/<run_id>/<seq>.json` plus a
`cursor.json` sidecar (`:156-158, 206-211`), with atomic writes
(`_atomic_write_text`, `:34-61`), `CorruptedCheckpointError` on bad JSON
(`:64-69, 180-191`), and `load_latest` falling back past a corrupt
checkpoint (`:160-178`). `list_checkpoints` ignores non-numeric stems
(`:193-204`) — deliberately tolerant of future sidecar files.

**Nothing stores a graph or a wiring artifact.** `Graph.version` exists only
as a passive string inside checkpointed state (`Context.graph_version`,
`executor.py:122`; `Provenance.graph_version`, `schema.py:31`). Postgres and
Temporal backends are `NotImplementedError` stubs (`:232-291`).

**Reusable seam:** `_atomic_write_text` and the per-run directory layout are
directly reusable for a versioned wiring/trace archive.

---

## 6. Evaluation: scoring exists, a *suite* does not

`Evaluator.evaluate(state) -> EvaluationRecord`
(`aef/services/eval/base.py:44-49`). `EvaluationRecord` (`:15-30`):
`run_id`, `task_completion`, `tool_call_accuracy|None`,
`trajectory_quality|None`, `cost_tokens`, `cost_dollars|None`,
`latency_ms|None`, `domain_gates: dict[str, bool]`, `metadata`. `passed` =
`task_completion >= 0.5 and all(domain_gates.values())` (`:41`, ADR 0038).

`RuleBasedEvaluator` (`rule_based.py:24-77`) computes task_completion from
`plan.status`/`errors` (`:29-36`), tool_call_accuracy from `tool_results`
`.get("error")` truthiness (`:62-67`), trajectory_quality from
`plan.status` (`:69-77`), cost_tokens by summing provenance (`:43`),
latency_ms from provenance timestamp spread (`:52-60`); `cost_dollars` is
always `None` — no pricing table exists (`:44-47`). `domain_gates:
dict[str, GateFn]` where `GateFn = Callable[[AEFState], bool]` (`:21`),
evaluated fresh per call (`:49`).

**The gap that matters most:** `evaluate()` takes exactly one completed
`AEFState`. There is **no suite abstraction** — no test-case/fixture
corpus, no expected-output pairing, no batch runner, no aggregation, and
`EvaluationRecord`s are returned but **never persisted anywhere**.
Comparing two graph *versions* requires running both over a shared input
corpus, and that corpus does not exist as a concept.

---

## 7. Memory, reflection, optimizer, Services

**Memory** (`aef/services/memory/base.py`): `MemoryKind` includes
`"failure"` and `"success"` (`:17-25`) — the lesson kinds a self-improving
loop needs already exist. `MemoryRecord` (`:28-42`); `write`, `query(kind,
*, run_id, agent_id, tags, limit)`, `get` (`:44-66`). `query()` filters on
**kind + run_id + agent_id + tag-superset only** (`:60-61`,
`in_memory.py:41-42`) — no content search, no similarity, no time range, no
multi-kind. A proposer cannot mine lessons semantically today.

**Reflection** (`aef/reasoning/reflection.py`): `Critique(verbal_feedback,
grounded_in)` (`:17-20`), `Judgment(score, rubric, rationale)` (`:29-33`);
`Critic.critique` and `Judge.judge` are Phase-3 stubs that raise
(`:23-26, 36-39`). `docs/design/phase3-reflection-critic-judge-brainstorm.md`
already scopes a rule-based-first slice and flags that `Services` has no
`critic`/`judge` slots.

**Optimizer** (`aef/services/optimizers/base.py`):
`OptimizationCandidate(target_node_id, description, payload,
predicted_improvement)` (`:19-24`); `propose(records:
list[EvaluationRecord])` raises (`:27-30`). Note it targets a **node's
payload (prompts)** — structural change is `MutationCandidate`'s domain.

**Services** (`contracts.py:47-101`): slots for `model_provider`, `memory`,
`graph_store`, `retriever`, `evaluator`, `tracer`, `tools`,
`policy_engine`, `optimizer`, `durability`, `hitl_approvals`, `clock`.
**There is no `critic`, `judge`, or `mutation_proposer` slot.**

---

## 8. The evolution engine: declared, and firmly disabled

`aef/evolution/engine.py` (108 lines) declares `MutationProposer`,
`ArchiveStore`, `EvalGate`, `CanaryController`, `MutationCandidate`,
`EvolutionConfig`. **Every abstract method raises**
`"<Class> is a Phase 4 interface; evolution is disabled"` (`:66-107`).
`MutationCandidate` (`:58-63`) carries `graph_id`, `description`,
`diff_summary: str` — a **free-form string**, not a structured diff — and
`predicted_improvement`.

**Disablement is dual-layer and must remain intact:**
- `EvolutionConfig.__post_init__` raises `NotImplementedError` if
  `enabled=True`, naming every unmet criterion (`engine.py:48-55`).
- `EvolutionSettings._must_stay_disabled` raises a pydantic `ValueError` at
  config-load time (`aef/config/schema.py:79-88`).

### 8.1 The seven Phase-4 gate criteria (verbatim, `engine.py:11-30`)

1. **Shadow execution** — every structural mutation runs against live
   traffic in read-only, no-side-effect mode for a minimum trace count
   before it is even eligible for promotion.
2. **Null-hypothesis baseline** — a randomized-mutation control group must
   be beaten, not just an absolute score threshold.
3. **Golden-trace regression** — every promoted graph version must still
   pass 100% of the accumulated golden-trace corpus; the corpus is never
   allowed to shrink.
4. **Bounded mutation rate** — at most K structural mutations per graph per
   time window.
5. **Cumulative-drift monitoring** — track accumulated sub-threshold edits;
   a documented failure mode where several compliant edits produced a later
   regression.
6. **Canary rollout** — stratified by tenant tag, gated on percentiles not
   means, previous stable version kept warm ≥24h so rollback never
   cold-starts.
7. **Human-in-the-loop approval** above a configurable risk threshold, with
   signed release manifests.

**Relationship to this program.** These seven criteria gate *unsupervised
runtime auto-promotion* — an agent's change going live with no human. This
program does not do that: the owner reviews and approves every change
before it reaches `main`, which is a **strictly stronger** promotion gate
than criterion 7 and replaces the need for criteria 1 and 6 (no unattended
live promotion occurs at all). Criteria 3, 4, and 5 remain directly
relevant and are carried into this design as automated gates. **The
evolution engine stays disabled throughout; this program neither enables it
nor weakens either disablement layer.**

---

## 9. Gaps — what must be built, stated plainly

| # | Gap | Evidence |
|---|---|---|
| G1 | No declarative graph/wiring spec, and no loader — graphs exist only as imperative `build_graph()` calls | `cli/run.py:67-70, 83`; no `to_dict`/`from_dict` in kernel |
| G2 | A `Graph` cannot be serialized at all (`Node.fn`, `Edge.condition` are callables) | `contracts.py:192-229` |
| G3 | `GraphDiff` is not persistable, misses edge reorder and unversioned node-body changes, has no modified-pairing | `graph.py:76-92, 127-143` |
| G4 | No trace serializer (`Context`, `END` sentinel have no JSON form) | `contracts.py:104-131, 159-174` |
| G5 | No golden-scenario/trace corpus, and no "never shrinks" enforcement | absent; named by criterion 3 |
| G6 | Replay cannot detect wiring regressions (routing never re-resolved) | `replay.py:47, 80-110` |
| G7 | No eval **suite**: `evaluate()` scores one state; no fixture corpus, batch runner, or aggregation | `eval/base.py:44-49` |
| G8 | `EvaluationRecord`s are never persisted; `Optimizer.propose` presumes a batch nothing collects | `optimizers/base.py:29` |
| G9 | No graph-version archive or rollback substrate | `durability.py:72-102`; `engine.py:77-83` stubs |
| G10 | `MutationCandidate.diff_summary` is a free-form string — no structured, applyable, reviewable diff | `engine.py:58-63` |
| G11 | No `critic`/`judge`/`proposer` slot in `Services`; Critic/Judge are stubs | `contracts.py:52-68`; `reflection.py:23-39` |
| G12 | Memory `query()` cannot search by content or similarity | `memory/base.py:51-59` |
| G13 | HITL is per-edge, per-run only — no approval workflow for a graph-version promotion | `contracts.py:67` |

---

## 10. Seams the design will actually use

- `Graph.compile()`/`validate()` (`graph.py:44-74`) — Gate 1, as-is.
- `GraphExecutor.run(record_trace=True)` (`executor.py:133-143`) — corpus
  recording and candidate re-execution.
- `ReplayEngine.replay()` (`replay.py:40`) — node-determinism regression
  (not wiring; see §3.1).
- `_resolve_route` (`executor.py:233-260`) — the live routing validator a
  rewired graph is genuinely exercised against.
- `RuleBasedEvaluator` + `EvaluationRecord.passed` (`rule_based.py`,
  `base.py:41`) — Gate 3's scoring primitive.
- `_atomic_write_text` + per-run dir layout (`durability.py:34-61`) —
  archive substrate.
- `MemoryKind` `"failure"`/`"success"` (`memory/base.py:17-25`) — lesson
  storage for a grounded proposer.
- `Services` DI (`contracts.py:47-101`) — where a proposer/critic/judge is
  injected, per the two-plane invariant.

---

**Next:** `01-architecture.md` — the system built on these seams, and the
answer to G1/G2 (how a wiring becomes reviewable data).
