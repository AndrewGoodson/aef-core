# ADR 0210: Bind replay to the recorded retrieval configuration

Status: accepted. Reproduced during the owner-authorized integration review.

## Evidence

A CLI run used `context: {impl: memory, token_budget: 1}` and a durable
failure record matching its billing objective. Its deterministic node asked
the retriever for 2,000 tokens and correctly received no chunks because the
configured ceiling was one token. Harvest reconstructed the recorded memory
but constructed a default retriever. That replay returned the matching chunk
and rejected the valid run as nondeterministic. The same run without the
configured ceiling reproduced and was promoted.

The regression exercised `run_graph_module`, durable-memory capture, harvest
and both evaluation runners. Before this change, its configured case failed
and its default control passed. Replaying memory alone was insufficient:
retrieval settings also change which evidence reaches the agent.

## Decision

`RecordedRun` and `Scenario` carry optional `context_config`, validated by the
existing strict `ContextConfig` schema. The recorder reads the actual built-in
`MemoryRetriever` before executing the graph and captures its token ceiling,
knowledge boost, staleness half-life and minimum knowledge occurrences. Resolved
numeric defaults are recorded too. This applies to CLI run recording and the
shared recorder used by loop record/bootstrap.

Harvest passes this binding through the determinism check, redaction
re-execution and corpus promotion. The in-process runner and isolated worker
rebuild the retriever through `build_retriever` over the scenario's replay
memory and derived knowledge. The worker receives only the validated settings
supplied by the parent; it does not read candidate YAML to configure retrieval.

This field cannot contain a provider, command, arbitrary serialized service,
policy or credential. Unknown fields and unsupported implementations are
refused by the schema. Live model permission still comes exclusively from
the existing explicit base-ref opt-in; captured retrieval settings do not
grant it. The policy used by gates remains the policy supplied by their caller
from the base ref, not a policy asserted by a recorded scenario.

## Compatibility and limits

Missing or null `context_config` preserves the default retrieval behavior of
older recordings. Existing payloads remain readable and are not silently
backfilled from current repository configuration. This is an additive field,
not a trace-format change. Existing positional `Scenario` arguments keep their
order; the replay fields follow the original `source` argument.

The binding covers the four knobs supported by `ContextConfig`. It does not
serialize arbitrary retrievers, custom candidate limits/kinds, service objects
or externally supplied knowledge. Custom retriever subclasses are not captured.
Like the existing memory snapshot contract, this is a defined supported replay
path rather than a claim that every injected `Services` object is reproducible.

The review also traced policy and reflection construction. Harvest still uses
the default policy; gate runners receive policy explicitly. Custom reflection
implementations, reflection model settings and judge rubrics are not captured
by this field. Runs depending on those unbound inputs may still fail the
determinism check. This change makes no claim that those configurations replay
identically and does not broaden their permissions to make them pass.

## Validation

`tests/harness/test_context_replay.py` checks the configured token ceiling
through CLI capture, harvest, corpus reload, in-process replay and an isolated
worker. Encoded traces match the original; the isolated comparison omits the
proxy's idempotency-key metadata. The durable source-memory file remains
byte-identical after harvest and both replays.

The default-budget control also executes both runners after removing the new
field to exercise legacy payloads. Separate cases cover absent/null loading,
all four settings through the shared recorder and worker, and rejection of
provider/policy fields, invalid token ceilings and unsupported implementations.
An existing positional constructor is also checked through payload round-trip.
All checks run offline without a live model provider.
