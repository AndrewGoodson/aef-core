# Architecture Decision Records

Nygard format. Written whenever the research report and research brief
disagreed, or whenever a design choice wasn't fully pinned down by either
source document — per the build instruction to never silently pick one
side of a conflict.

| ADR | Decision | Confidence |
|---|---|---|
| [0001](0001-thin-graph-ir-not-a-framework.md) | Thin custom graph IR, not a framework wholesale | High |
| [0002](0002-durability-backend-in-memory-and-file-json.md) | Phase 0/1 durability: InMemory + File(JSON), not Postgres/Temporal | High |
| [0003](0003-knowledge-graph-backend-deferred.md) | KG backend deferred to Phase 2; target Neo4j/FalkorDB, not Apache AGE | Medium |
| [0004](0004-memory-backend-mem0-default.md) | Mem0 is the Phase 1 memory default; temporal-KG memory deferred | High |
| [0005](0005-multi-agent-default-single-agent-with-readers.md) | Single-agent-with-readers default; deterministic handoff over emergent routing | High |
| [0006](0006-evolution-engine-disabled-by-default.md) | Evolution engine disabled by default, enforced in code not just config | High |
| [0007](0007-fan-out-declared-not-executed.md) | Fan-out declared in the contract, not executed until Phase 2 | High |
| [0008](0008-otel-genai-attributes-pinned-locally.md) | OTel GenAI attribute keys pinned locally, not imported from the incubating package | High |
| [0009](0009-checkpoint-resume-requires-a-cursor.md) | Resuming a run needs a persisted cursor — `run()` alone silently duplicates side effects | High |
| [0010](0010-idempotency-key-is-exposed-not-enforced.md) | Kernel computes/exposes the idempotency key; enforcing it is the node's job, not the kernel's | High |
| [0011](0011-edge-and-node-observability-fields-wired-up.md) | HITL-approval edges now actually block; emergent-routing and telemetry tags now actually surface | High |
