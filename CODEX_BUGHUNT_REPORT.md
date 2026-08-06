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

## Round 6 — boundary values and hostile identifiers

### Looked at

Identifier/path boundaries, checkpoint sequence semantics, collection limits,
retrieval budgets, empty and negative values, and the agreement between public
contracts and backend behavior.

### Confirmed and fixed

Four boundary defects were reproduced:

1. `FileDurabilityBackend` applied its run-id containment check to writes and
   `load_latest()`, but not to `load_checkpoint()`, `list_checkpoints()`, or
   `load_cursor()`. A read using `../outside/victim` successfully loaded a
   sibling backend's checkpoint or cursor. Read-only calls also created the
   requested run directory as a side effect.
2. `AEFState` accepted a negative `checkpoint_seq`. The file backend wrote
   `-1.json`, while checkpoint discovery recognizes only digit-only stems, so
   the successfully saved checkpoint immediately disappeared from listings.
3. Both memory backends accepted a negative query `limit`. The in-memory
   backend interpreted `-1` as Python's “all but the last item” slice, while
   the Mem0 adapter sent `top_k=-1` to the provider and then sliced its result.
4. `MemoryRetriever` accepted zero or negative `candidates_per_kind` and
   `max_token_budget` at construction. These invalid caps survived until
   retrieval, producing empty or contradictory behavior instead of a clear
   configuration error.

Reproduction before the fixes:

```text
pytest -q <ten boundary regressions>
10 failed

load_checkpoint('../outside/victim', 0): returned sibling checkpoint
list_checkpoints('../outside/victim'): returned [0]
load_cursor('../outside/victim'): returned 'node_b'
AEFState(checkpoint_seq=-1): validated successfully
InMemoryMemoryStore.query(limit=-1): returned all but the last match
Mem0Adapter.query(limit=-1): called the provider with top_k=-1
MemoryRetriever with each zero/negative cap: constructed successfully
```

Expected: an untrusted run id cannot escape the durability root on any read or
write; checkpoint sequence values agree with the backend's discoverable file
format; query limits are non-negative and consistent across adapters; and
invalid retrieval caps fail at the configuration boundary.

Fixes: route every durability path through one validated single-segment
resolver and avoid directory creation on reads; constrain checkpoint sequence
to non-negative integers; define and enforce non-negative memory query limits
with zero as an empty query; and validate retriever caps in `__post_init__()`.
Each regression passed after its narrow fix.

The durability defect violated the backend's documented containment boundary,
and the negative-sequence defect violated the save/list round-trip property.
The two limit defects violated behavioral substitutability between the real
memory backends and allowed invalid configuration to masquerade as a valid
empty result.

### Ruled out

- Empty and missing durability runs return `None` or an empty list without
  creating directories.
- Zero memory query limits now return no records consistently; Mem0 identity
  scope is still validated before that early return.
- Existing positive retrieval caps and finite token budgets preserve their
  previous ordering and truncation behavior.
- Previously covered path classes (null bytes, backslashes, symlink modes, and
  case variants) were not re-reported as new findings.

### Round gate

- `pytest -q`: 1426 passed, 93 warnings
- `mypy --strict aef`: 107 source files clean
- `ruff check .`: clean
- `ruff format --check aef tests examples`: 193 files already formatted
- MindGraph verification: 287 checks passed; self-test detected all 29 planted failures with no false positives

## Round 7 — swallowed failures and resource lifecycle

### Looked at

Broad exception handlers, subprocess ownership, worker startup and graph
reconstruction, process-group termination, container cleanup, sandbox timeout
paths, tracing context managers, halt notification, corpus loading, atomic file
writes, and temporary-state use.

### Confirmed and fixed

The isolated evaluation path had one subprocess-lifecycle defect with three
observable parts:

1. A worker that printed a syntactically valid but type-invalid handshake such
   as `{"graph": null}` raised `TypeError` outside `_handshake()`'s explicit
   cleanup branches. `NodeWorkerSession.__init__()` then failed while the
   already-started child kept running.
2. After a valid session started, an exception from parent-side graph
   reconstruction or compilation returned failed scenario results without
   closing that session.
3. `NodeWorkerSession.close()` killed a live process but did not wait for it,
   leaving child reaping to a later, unrelated `Popen` cleanup pass.

Reproduction before the fix:

```text
pytest -q tests/harness/test_isolated_evaluation.py \
  -k 'malformed_handshake or reconstruction_failure'

2 failed
malformed {"graph":null}: os.waitpid(pid, WNOHANG) reported the worker still alive
parent graph reconstruction failure: session.closed was False
```

Expected: once `Popen` succeeds, every exit from initialization and parent
setup terminates and reaps the owned worker before the gate returns.

Fix: make initialization cleanup unconditional for every `BaseException`,
validate the graph frame is an object, close an acquired session on parent
graph-setup failure, and wait after killing a live worker. The regression uses
a real sleeping child and verifies that it is no longer waitable by the parent;
the reconstruction test verifies both the explicit closed marker and a reaped
return code.

This violated ADR 0093/0095's process-lifetime containment claim: the parent
reported evaluation complete while candidate code could still be executing.

### Ruled out

- Sandbox command timeouts kill the whole process group and then reap through
  `communicate()`.
- Contained shadow graph construction already closes its session on every
  `BaseException` after acquisition.
- Candidate node failures are intentionally converted into failed scenario or
  shadow outcomes; they are not silently accepted as passing evidence.
- Gate exceptions become explicit failed gate results, cohort-construction
  failures preserve G2/G3 refusal, and halt-notification delivery failures are
  returned to the caller.
- Tracing context managers record raised exceptions and end/detach spans in
  `finally` blocks.
- Container forced removal suppresses only secondary cleanup errors so it does
  not replace the primary timeout result.

### Suspected, deferred

- `_atomic_write_text()` can leave its fixed-name temporary file behind if a
  disk write, fsync, or replace fails. A subsequent same-process write truncates
  that path, and no production corruption or unbounded accumulation was
  reproduced, so it is not classified as a defect here.
- The test suite itself has legacy `tempfile.mkdtemp()` fixtures without
  explicit removal. They do not establish a production runtime defect.

### Round gate

- `pytest -q`: 1428 passed, 93 warnings
- `mypy --strict aef`: 107 source files clean
- `ruff check .`: clean
- `ruff format --check aef tests examples`: 193 files already formatted
- MindGraph verification: 287 checks passed; self-test detected all 29 planted failures with no false positives


## Round 8 — CLI adoption and doctor hostile inputs

### Looked at

Adoption into empty and partially populated repositories, dangling leaf
symlinks, symlinked output directories, ordinary-file parents, preservation of
existing files, adopted-repository detection, adapter shape validation,
generated placeholders, invalid Python, invalid YAML, and undecodable input.

### Confirmed and fixed

Three CLI defect classes were reproduced:

1. `aef adopt` followed repository-controlled symlinks. `Path.exists()` is
   false for a dangling symlink, so a `CLAUDE.md` link caused adoption to
   create its target outside the repository. A `.github` directory symlink
   likewise caused Copilot instructions and both workflow files to be written
   into an external directory.
2. `aef doctor` could report an adopted adapter as healthy when it was not
   usable. Removing the generated adapter made the repository look
   non-adopted, a nested `build_graph()` satisfied the AST scan despite not
   being importable from the module, and the untouched generated stub was
   emitted as `ok=True` even though its advisory text said it was not wired.
3. Non-UTF-8 `aef_adapter.py` or `aef.yaml` files raised raw
   `UnicodeDecodeError` exceptions. Doctor and the config loader therefore
   crashed instead of returning the named diagnostic/readable
   `AgentConfigError` their contracts promise.

Reproduction before the fixes:

```text
run_adopt(repo containing CLAUDE.md -> ../outside/CLAUDE.md):
  created ../outside/CLAUDE.md
run_adopt(repo containing .github -> ../outside):
  created copilot-instructions.md and two workflow files in ../outside

run_doctor(adopted repo after unlinking aef_adapter.py):
  no adapter failure
run_doctor(adapter with only nested build_graph):
  adapter_importable OK
run_doctor(pristine generated adapter):
  adapter_importable ok=True, detail="still the generated stub"

pytest -q \
  tests/cli/test_doctor.py::test_an_adapter_that_is_not_utf8_is_reported \
  tests/config/test_schema.py::test_load_agent_config_non_utf8_raises_readable_error
2 failed with uncaught UnicodeDecodeError
```

Expected: adoption writes only beneath its target without following links;
doctor identifies an adopted repository independently of the adapter it is
checking and requires a top-level callable entrypoint; incomplete generated
artifacts are visibly warnings, not successes; malformed text produces an
actionable diagnostic rather than a traceback.

Fixes: reject an existing/symlinked leaf and any symlink or non-directory in
an output path's parent chain; recognize adoption marker files; require a
top-level `build_graph()`; make the generated stub an advisory failure; and
translate decoding failures at both file-reading boundaries. Regression tests
cover every reproduced shape.

The external writes violated `aef adopt`'s repository-scoped, never-overwrite
contract. The false-green checks contradicted ADR 0079's claim that doctor
detects an unwired adapter. The raw decoding failures contradicted the config
loader's stated readable-error guarantee.

### Ruled out

- Existing regular output files remain byte-for-byte unchanged and are listed
  as skipped.
- A normal pristine adoption still creates the complete expected file set.
- A fresh `aef init` repository remains valid without `CLAUDE.md`; adopted
  marker files retain the stricter checks.
- Invalid Python and invalid YAML still become named doctor failures without
  importing adopter code or executing module-level side effects.
- Descendants of a regular file used as a would-be directory are skipped
  rather than overwritten or traversed.

### Round gate

- `pytest -q` (with `.venv` activated): 1435 passed, 93 warnings
- `mypy --strict aef`: 107 source files clean
- `ruff check .`: clean
- `ruff format --check aef tests examples`: 193 files already formatted
- MindGraph verification: 287 checks passed; self-test detected all 29 planted failures with no false positives

## Round 9 — harness isolation and immutable candidate snapshots

### Looked at

Base/head ref resolution, candidate size accounting, raw diff inspection,
base-ref lifetime, workspace destination state, symlink leaves, executable Git
modes, `.gitattributes`, `.gitignore`, submodule and symlink entries, unusual
Git configuration, and overlay-path containment.

### Confirmed and fixed

Five isolation defects were reproduced:

1. `read_candidate()` inspected a movable branch name more than once and only
   resolved its SHA afterward. A ref moved between the numstat and raw-diff
   commands could therefore combine the size of one candidate with the paths
   and recorded SHA of another candidate. The regression advances a real Git
   ref after numstat and observed the large replacement commit accepted under
   the small commit's size measurement.
2. `BaseRefHarness.base_sha` claimed to pin the trusted base at construction,
   but resolved `base_ref` on every property access. Advancing the ref after
   constructing the harness changed which evaluator bytes it materialized.
3. `build_candidate_workspace()` accepted a nonempty destination. Stale files
   absent from both the base tree and candidate diff survived in the evaluated
   workspace, so it was not the claimed exact post-merge tree.
4. A destination leaf symlink was followed, allowing materialization outside
   the caller's selected scratch directory.
5. Base files recorded by Git as executable (`100755`) were emitted with the
   process default regular-file mode. A real executable base script therefore
   lost all execute bits in the candidate workspace.

Reproduction before the fixes:

```text
pytest -q \
  tests/harness/test_candidate.py::test_a_moving_head_ref_cannot_mix_two_candidate_snapshots \
  tests/harness/test_trust.py::test_the_base_sha_stays_pinned_when_the_ref_moves \
  tests/harness/test_gates.py::test_workspace_refuses_a_nonempty_destination \
  tests/harness/test_gates.py::test_workspace_refuses_a_symlink_destination \
  tests/harness/test_gates.py::test_workspace_preserves_executable_files_from_base

5 failed
moving ref: recorded head SHA was the replacement 600-line commit
base harness: base SHA changed after ref advance
nonempty destination: no exception; stale file remained
symlink destination: no exception; external target was populated
executable base file: mode & 0o111 == 0
```

Expected: both diff phases use the same immutable object IDs; trusted base
selection cannot change during a run; materialization starts from an empty,
non-symlink directory; and ordinary Git executable modes survive reconstruction.

Fixes: resolve both refs before either candidate-inspection command and use
only their immutable SHAs; cache the base SHA in the frozen harness during
construction; share a destination validator that rejects symlink and nonempty
leaves; preserve `100755` versus `100644` modes; and set candidate overlay
files to the regular non-executable mode. The focused reproduction passed all
five tests after the fixes. Commits: `95a4c3e`, `9363e23`.

These defects contradicted ADR 0047's immutable-base and clean reconstructed
workspace claims. The ref race was the highest impact: it allowed the artifact
that passed the size boundary to differ from the artifact whose changed paths
and SHA proceeded through the gates.

### Ruled out

- Committed files ignored by `.gitignore` remain present because reconstruction
  enumerates Git objects rather than the working tree.
- Export-ignore and content filters do not remove committed base files from the
  object-based workspace path; binary candidate changes remain fail-closed.
- Candidate symlink and submodule modes are rejected before overlay; base
  symlinks are deliberately skipped under the documented policy.
- Rename detection is explicitly disabled, and object reads do not invoke
  working-tree clean/smudge filters or depend on line-ending checkout config.
- Existing path validation continues to reject traversal, null bytes,
  backslashes, case variants, and directory/file collisions; those previously
  documented classes were not re-reported.

### Round gate

- `pytest -q` (with `.venv` activated): 1440 passed, 93 warnings
- `mypy --strict aef`: 107 source files clean
- `ruff check .`: clean
- `ruff format --check aef tests examples`: 193 files already formatted
- MindGraph verification and planted-failure self-test: both exited cleanly
