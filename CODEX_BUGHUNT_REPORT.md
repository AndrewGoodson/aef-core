# Codex 10-round adversarial bug hunt

Branch: `codex/bughunt-10x`

Base: `b7e926a6a369a59bd0d5b23b6fcf211da6e5d52c`

## Baseline

The documented environment (`source .venv/bin/activate`) started green:

- `pytest -q`: 1398 passed
- `mypy --strict aef`: 107 source files clean
- `ruff check .`: clean
- `ruff format --check aef tests examples`: 192 files formatted
- `cd mindgraph && python tools/verify`: 287 checks passed
- `cd mindgraph && python tools/verify --self-test`: 29 detections passed

An initial invocation of `.venv/bin/pytest -q` without activating the virtual
environment produced 18 subprocess failures because child processes resolved a
different `python`. That was an invalid test environment, not a product defect.

## Round 1 — replay determinism and checkpoint round-trips

### Looked at

`aef/kernel/replay.py`, `executor.py`, `durability.py`, their checkpoint/cursor
tests, deterministic replay, fallback-route verification, corrupt-checkpoint
rewind, and HITL resumption.

### Confirmed and fixed

`FileDurabilityBackend.load_cursor()` accepted schema-invalid but syntactically
valid JSON. `{"next_node": 7}` and `{}` returned `None`, the same value used for
a completed run; arrays and strings leaked `AttributeError`. A real
`GraphExecutor.resume()` probe therefore silently returned the last checkpoint
without executing the pending node.

Expected: external cursor corruption raises the named
`CorruptedCheckpointError`; it must never become a completed-run signal.

Reproduction before the fix:

```text
pytest -q tests/kernel/test_durability.py -k invalid_schema
4 failed: two DID NOT RAISE CorruptedCheckpointError; two raised AttributeError
```

Fix: validate that the decoded cursor is an object containing `next_node`, and
that its value is a string or null. The regression test covers numeric,
missing, array, and scalar payloads. After the fix, all 18 cursor tests pass.

### Ruled out

- Deterministic nodes are re-executed against the recorded input state.
- Replay verifies both ordinary and fallback routes.
- Trace records deep-copy state and delta snapshots.
- Latest-checkpoint recovery falls back past corrupt newest checkpoints but
  still fails loudly when none are loadable.
- HITL resume preserves the pending route and does not re-run the gated node.

### Suspected, not yet reproduced

Read operations in `FileDurabilityBackend` do not consistently use the same
run-id containment helper as writes. Reserved for the boundary-values round;
no change made in this round.

## Round 2 — deny-by-default policy and HITL routing

### Looked at

`aef/security/tool.py`, `aef/kernel/contracts.py`, the executor's gated-edge
resolution, audit-writer failure behaviour, scope/name/risk ordering, and the
policy and executor regression suites.

### Confirmed and fixed

`PolicyEngine.__init__()` selected injected dependencies with boolean `or`.
A valid caller-supplied `AuditLogWriter` whose domain-defined truthiness was
false was silently replaced by an in-memory writer. The policy decision still
returned normally, but the supplied durable audit received no entry.

Expected: dependency injection distinguishes only “not supplied” (`None`) from
an explicit implementation. It must not interpret a dependency's truthiness.

Reproduction before the fix:

```text
decision= allow
uses_supplied_writer= False
supplied_entries= 0

pytest -q tests/security/test_tool.py::test_explicit_falsey_audit_log_dependency_is_honored
FAILED: engine.audit_log is an unexpected InMemoryAuditLogWriter
```

Fix: use explicit `is not None` selection for the config, audit writer, and
clock dependencies. The regression supplies a falsey writer and verifies both
object identity and the actual appended record. All 18 policy tests pass.

This contradicts the DI-only service contract and the “full audit trail” claim
in `CLAUDE.md`: prior to the fix, a valid explicit audit dependency could be
ignored without error.

### Confirmed, intentionally not changed

HITL approval keys are ambiguous. `hitl_approval_key("a->b", "c")` and
`hitl_approval_key("a", "b->c")` both serialize as `a->b->c`. A compiled graph
with the gated edge `("a", "b->c")` accepted an approval minted for the
different edge `("a->b", "c")` and executed the destination node:

```text
wrong_edge_approval= a->b->c
gated_edge_key= a->b->c
crossed= True
```

This violates ADR 0011's claim that approvals are edge-specific and explicit.
It is a safety-relevant authorization collision. No fix or regression test was
committed because the bug-hunt brief's hard stop says not to alter routing into
a HITL-gated edge. The owner should choose a collision-free approval identity
and migration policy before unattended use with caller-controlled node IDs.

### Ruled out

- A tool/call name mismatch is denied before forbidden-name, scope, and risk
  checks, and the denial is audited.
- Missing scopes and scope-less tools remain deny-by-default.
- Non-finite and out-of-range risks and HITL thresholds are rejected at
  construction, including the maximum-risk/maximum-valid-threshold boundary.
- A writer exception propagates instead of returning an unaudited decision.
- Without the delimiter collision, an approval for a different ordinary edge
  is rejected and ungated edges remain unaffected.

### Suspected, not changed in this round

`InMemoryAuditLogWriter` stores `ToolCall.arguments` by reference, so caller
mutation may rewrite audit history. Reserved for the shared-mutable-state
round; not yet reproduced here.

## Round 3 — provider fallback and vendor error boundaries

### Looked at

`aef/providers/base.py`, `aef/providers/anthropic_provider.py`, the installed
Anthropic SDK's exception and request types, fallback ordering, aggregate
failure reporting, translation failures, metadata, and injected-client
construction.

### Confirmed and fixed

`AnthropicProvider.__init__()` selected its injected client with boolean `or`.
A valid falsey client was discarded and a new vendor client was constructed.
The call then used the constructed client, crossing both the caller's DI and
network/configuration boundary.

Expected: only `None` means “construct the default SDK client.” An explicit
implementation must be used regardless of domain-defined truthiness.

Reproduction before the fix:

```text
constructor_called=True
result_content=constructed

pytest -q tests/providers/test_anthropic_provider.py::test_explicit_falsey_client_dependency_is_honored
FAILED: expected 'injected', got 'constructed'
```

Fix: use an explicit `client is not None` selection. The regression verifies
both the returned content and that `anthropic.Anthropic()` was never called.
All 16 provider tests pass.

This contradicts the repository's DI-only contract and the adapter's stated
purpose of permitting fake-client injection without network access. In an
application, it could silently replace a controlled client with one using
ambient vendor configuration.

### Ruled out

- Fallback stops after the first success and reaches a third provider after
  two ordinary provider failures.
- When all providers fail, the aggregate error names every provider and
  preserves every reason.
- Adapter-programming errors outside the vendor exception hierarchy propagate
  instead of being mislabeled and silently retried.
- Every installed Anthropic SDK exception derives from `AnthropicError` at the
  adapter boundary, including the non-`APIError` path pinned by ADR 0037.
- `metadata.user_id` is passed through and unrelated vendor-neutral metadata is
  deliberately omitted as documented in ADR 0015.

### Suspected, not changed

The vendor-neutral `Role` type admits `"tool"`, but the Anthropic adapter
forwards that string as a message role. The installed SDK's `MessageParam`
contract admits only `user`, `assistant`, and `system`; Anthropic tool results
are structured content blocks, which `ProviderMessage(content: str)` cannot
represent. No repository caller currently constructs a tool-role message, and
no live API call was made, so this is an interface mismatch rather than a
confirmed production failure in this round.

### Round gate

- `pytest -q`: 1404 passed
- `mypy --strict aef`: 107 source files clean
- `ruff check .`: clean
- `ruff format --check aef tests examples`: 192 files formatted
- MindGraph verification: 287 checks passed; self-test 29 detections passed

## Round 4 — concurrency and shared mutable state

### Looked at

The in-memory audit, memory, durability, and tracing backends; fallback-provider
construction; graph/container ownership; state/delta snapshot semantics; and
concurrent reads and writes against mutable stores.

### Confirmed and fixed

Four boundaries retained caller-owned mutable data after the API operation had
logically completed:

1. `InMemoryAuditLogWriter.write()` stored the original `AuditEntry`. Although
   its dataclasses are frozen, nested `ToolCall.arguments` are not. Mutating the
   caller's nested dict rewrote the recorded security decision's history.
2. `InMemoryMemoryStore.write()` stored the original `MemoryRecord`, and both
   `get()` and `query()` returned the stored object. A writer or reader could
   therefore rewrite durable-in-process memory without another `write()`.
3. `FallbackProvider` retained the constructor's list. Clearing it after the
   non-empty invariant check produced `ModelProviderError('all providers
   failed: ')` without calling a provider.
4. `InMemoryTracer` only shallow-copied the top-level attributes dict and
   retained values passed to `set_attribute()`. Later nested mutation rewrote
   already-recorded telemetry.

Direct reproduction before the fixes:

```text
audit_history_after_caller_mutation= {'nested': {'secret': 'after'}}
memory_after_input_mutation= {'nested': {'fact': 'after-write'}}
memory_after_output_mutation= {'nested': {'fact': 'after-read'}}
fallback_after_caller_list_clear= ModelProviderError 'all providers failed: '

pytest -q <the four ownership regressions>
4 failed

pytest -q tests/observability/test_in_memory.py::test_start_span_snapshots_nested_attributes
FAILED: recorded attempt changed from 1 to 2
pytest -q tests/observability/test_in_memory.py::test_set_attribute_snapshots_nested_value
FAILED: recorded attempt changed from 1 to 2
```

Expected: an audit entry, memory write/read, constructed fallback chain, and
recorded telemetry value are point-in-time snapshots. Later caller mutation
must not retroactively alter them.

Fixes: deep-copy audit and telemetry records at their ownership boundaries;
deep-copy memory content on write and read; and snapshot the fallback order as
a tuple. The audit copy deliberately fails closed if a value cannot be copied:
returning a policy decision while silently keeping a rewriteable audit record
would be the unsafe outcome.

### Confirmed concurrent-access defect and fixed

`InMemoryMemoryStore.query()` iterated `_records.values()` without
synchronization while `write()` could resize the dict. A two-thread stress
probe reproduced `RuntimeError: dictionary changed size during iteration`.
The committed regression forces the exact interleaving by suspending a query
comparison, completing a write, then resuming the invalidated iterator; it
failed deterministically before the fix.

```text
python <200000-write concurrent query probe>
['RuntimeError: dictionary changed size during iteration']

pytest -q tests/services/memory/test_in_memory.py::test_query_and_write_can_run_concurrently
FAILED: RuntimeError('dictionary changed size during iteration')
```

Expected: the real default memory backend may be shared by concurrent agent
work without leaking an implementation-level iteration failure. Fix: protect
compound write/query/get operations with an `RLock`, while preserving snapshot
returns. The deterministic regression now passes.

These defects contradict the claims that audit/telemetry are historical
records and that the in-memory memory backend is a real default backend. A
frozen outer dataclass was presentation, not isolation, until the nested
ownership boundary was enforced.

### Ruled out

- `Graph.__post_init__()` already snapshots node and edge collections and
  exposes the node map through `MappingProxyType`.
- State deltas and execution traces deep-copy ordinary mutable payloads; their
  documented fallback for non-copyable runtime handles is explicit.
- `InMemoryDurabilityBackend` round-trips checkpoints through JSON, preventing
  caller mutation from rewriting stored checkpoint content. A 200,000-write
  concurrent load/list stress probe did not reproduce a failure; this is not a
  proof of thread safety and no such guarantee is documented.
- Fallback ordering and all-failed aggregation still behave identically after
  converting the internal provider collection to a tuple.

### Suspected, deferred

`Services.tools` and `RuleBasedEvaluator.domain_gates` retain caller-owned
mappings despite frozen containers. No executing core path currently resolves
tools from `Services.tools`, and live evaluator reconfiguration may be an
intentional API choice, so neither was classified as a defect here. The
factory/config round will test whether configuration mutation crosses an
unexpected boundary.

### Round gate

- `pytest -q`: 1411 passed
- `mypy --strict aef`: 107 source files clean
- `ruff check .`: clean
- `ruff format --check .`: 192 files already formatted
- MindGraph verification: 287 checks passed; self-test detected all 29 planted failures with no false positives

## Round 5 — configuration, factories, and service wiring

### Looked at

Pydantic configuration boundaries, YAML loading, the CLI-to-runtime handoff,
`agent_services()`, memory-store construction, evaluator preflight wiring,
policy/context propagation, dependency defaults, and mutable configuration
ownership.

### Confirmed and fixed

Three configuration-to-runtime seams accepted one value and executed another:

1. `InMemoryMemoryStore(clock=...)` used boolean `or`, so a valid falsey clock
   dependency was discarded. A record expected to receive the injected
   `2020-01-02` timestamp instead received the current 2026 time.
2. Both `agent_services(judge_rubric={})` and `run_graph_module(...,
   judge_rubric={})` silently replaced an explicit empty rubric with
   `{"quality": 1.0}`. That bypassed `RuleBasedJudge`'s deliberate empty-rubric
   rejection and changed invalid caller input into a different evaluation.
3. `MemoryConfig` accepted `impl="mem0"` and accepted
   `impl="in_memory", backend="sqlite"`, but runtime construction always
   returned volatile `InMemoryMemoryStore`. The selected implementation and
   backend were not merely unavailable; they were ignored.

Reproduction before the fixes:

```text
falsey clock: expected 2020-01-02T00:00:00+00:00; observed current 2026 timestamp
agent_services(judge_rubric={}): no exception; quality rubric installed
run_graph_module(judge_rubric={}): no exception; graph ran successfully
MemoryConfig(impl="mem0"): validated; runtime still constructed in-memory storage
MemoryConfig(impl="in_memory", backend="sqlite"): validated; backend had no effect

pytest -q <five targeted regressions>
5 failed
```

Expected: only `None` selects a dependency default; explicit invalid rubric
input reaches the judge's validator; and a loadable configuration never claims
a runtime implementation or durability backend that its factory cannot build.

Fixes: use explicit `None` selection for the memory clock and judge rubric;
pass the CLI rubric unchanged to the shared factory; reject unwired memory
implementations and backends at schema validation with actionable errors.
This makes ADR 0014's known implementation limit fail loudly instead of
letting deployment configuration overstate persistence.

### Ruled out

- Pydantic list defaults are isolated between config instances.
- The supported `in_memory` configuration loads and builds normally.
- Policy, context-engine settings, and evaluator gate configuration are
  propagated or preflight-validated by the CLI path.
- The default judge rubric is copied for each service bundle, so mutating one
  judge does not alter subsequent defaults.

### Suspected, deferred

- `ModelProviderConfig.model` appears declarative while completion requests
  supply their own model. The provider/CLI paths need a concrete end-to-end
  disagreement before classifying this as a defect.
- The shipped Azure security example names `local-llama` as a fallback, while
  the runtime provider factory supports only its registered providers. This is
  reserved for CLI hostile-input testing.
- `Services.tools` and `RuleBasedEvaluator.domain_gates` still retain caller
  mappings. There is no demonstrated core consumer whose result is corrupted
  by later mutation.

### Round gate

- `pytest -q`: 1416 passed, 93 warnings
- `mypy --strict aef`: 107 source files clean
- `ruff check .`: clean
- `ruff format --check aef tests examples`: 193 files already formatted
- MindGraph verification: 287 checks passed; self-test detected all 29 planted failures with no false positives
