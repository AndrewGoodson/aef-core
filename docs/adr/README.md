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
| [0012](0012-toolcall-tool-name-must-match-the-tool-being-evaluated.md) | PolicyEngine now denies a ToolCall whose tool_name doesn't match the Tool it's evaluated against | High |
| [0013](0013-eval-record-unmeasured-fields-are-none-not-zero.md) | cost_dollars/latency_ms are None when unmeasured, not a misleading 0.0; latency_ms now actually computed | High |
| [0014](0014-config-to-services-wiring-is-partial-by-design.md) | `aef run --config` wires a real model_provider; full config-to-Services wiring needs a plugin registry (Phase 2) | High |
| [0015](0015-completion-request-metadata-now-passed-to-anthropic.md) | CompletionRequest.metadata.user_id now reaches Anthropic's own abuse-tracking field; FallbackProvider verified already correct | High |
| [0016](0016-adopt-detects-frameworks-from-manifests-too.md) | aef adopt now detects frameworks from requirements.txt/pyproject.toml, not just .py imports | High |
| [0017](0017-otel-span-record-exception-accepts-baseexception.md) | OtelSpan.record_exception now accepts BaseException, matching the real SDK and InMemorySpan | High |
| [0018](0018-aef-run-adds-cwd-to-syspath.md) | aef run adds CWD to sys.path — aef init's own output couldn't be run before this | High |
| [0019](0019-plan-replacement-footgun-in-the-shipped-example.md) | StateDelta.plan replaces not merges; the shipped example was silently dropping subgoals/reusable_key | High |
| [0020](0020-edge-equality-uses-condition-code-not-identity.md) | Edge equality compares condition by __code__ not identity — diff() falsely flagged every rebuilt graph as changed | High |
| [0021](0021-aef-run-checkpoints-dir-enables-eval-and-trace-chaining.md) | aef run --checkpoints-dir — before this, run/eval/trace could never be chained at all | High |
| [0022](0022-scores-must-be-finite.md) | scores reject inf/nan at construction — was silently corrupted to null on checkpoint write, crashed later on reload | High |
| [0023](0023-replay-validates-trace-chain-integrity.md) | replay() now validates trace chain integrity — a reordered/corrupted trace was silently replayed into a wrong result with no error | High |
| [0024](0024-adopt-claude-md-doc-paths-fixed-for-pip-installs.md) | aef adopt's generated CLAUDE.md no longer points pip-installed adopters at docs/roadmap.md, which never ships in the package | High |
| [0025](0025-numeric-field-sweep-hitl-nan-bypass.md) | ToolCall.risk/PolicyConfig NaN silently bypassed the HITL security gate (risk > NaN is always False) — now rejected at construction | High |
| [0026](0026-file-durability-backend-checkpoint-corruption-hardening.md) | FileDurabilityBackend: a stray non-numeric .json file bricked list_checkpoints for the whole run; corrupted checkpoints now raise a named, diagnosable error | High |
| [0027](0027-otel-tracer-nested-spans-now-actually-parented.md) | OtelTracer's nested spans exported as unrelated roots (no parent/child) in a real OTel backend — start_span() never attached the OTel active context | High |
| [0028](0028-graph-visualize-mermaid-injection-fix.md) | Graph.visualize(): a node id containing Mermaid syntax could break out of its label and inject extra flowchart statements — now uses synthetic ids + label escaping | High |
| [0029](0029-init-agent-name-path-traversal-fix.md) | aef init's agent_name had zero path validation — "../../evil" and absolute paths wrote files outside the intended agents/ directory | High |
| [0030](0030-mem0-adapter-get-no-longer-swallows-real-failures.md) | Mem0Adapter.get()'s bare except Exception silently turned genuine backend failures into indistinguishable-from-not-found — removed | High |
| [0031](0031-atomic-durability-writes-and-load-latest-recovery.md) | Durability writes are atomic (temp+fsync+os.replace); load_latest recovers past a torn checkpoint instead of bricking resume — completes ADR 0026's read-only story | High |
| [0032](0032-hitl-pause-is-always-resumable.md) | A HITL pause now persists a checkpoint+cursor before raising, so a run gated before its first checkpoint is resumable; gated node re-execution kept as documented at-least-once | High |
| [0033](0033-autonomy-protocol-is-a-versioned-artifact.md) | The autonomous self-improving loop + its HARD-STOP safety gates are a versioned repo artifact (docs/autonomy/self-improving-loop.md), not a chat prompt; adopt emits a pointer | High |
| [0034](0034-adopt-emits-the-onboarding-kit.md) | aef adopt now emits AGENT_INTEGRATION.md (ingest-and-start guide) + AUTONOMY.md (inlined safety contract) into adopted repos, never-overwrite | High |
| [0035](0035-hitl-threshold-bounded-below-one.md) | PolicyConfig.require_hitl_above_risk bounded to [0.0, 1.0) — a threshold >=1.0 made the HITL gate unreachable for max-risk calls (residual half of 0025) | High |
| [0036](0036-fallback-routing-bypasses-edge-conditions.md) | A node's fallback_node_id now routes unconditionally on exception, bypassing edge resolution — before, a missing/false-condition edge masked the error with RoutingViolationError and the handler never ran | High |
| [0037](0037-anthropic-adapter-catches-the-true-base-exception.md) | AnthropicProvider catches anthropic.AnthropicError not just APIError — non-APIError subclasses leaked raw and aborted FallbackProvider's chain | High |
| [0038](0038-eval-passed-requires-completion-and-gates.md) | EvaluationRecord.passed requires task completion AND all domain gates — a configured gate used to override task_completion, marking an errored run passed | High |
| [0039](0039-replay-trusts-fallback-records.md) | Replay trusts fallback records (is_fallback flag) instead of re-executing them — a deterministic node's fallback trace was unreplayable (crashed with the original exception); seam ADR 0036 exposed | High |
| [0040](0040-adopt-emits-cross-harness-entry-files.md) | aef adopt emits a native entry file per harness (AGENTS.md/Codex, .github/copilot-instructions.md, .cursor/rules/aef.mdc) so the scaffold works across Claude/Codex/Cursor/Copilot, not Claude-only | High |
| [0041](0041-wiring-manifest-is-the-self-rewiring-artifact.md) | Self-rewiring operates on a declarative wiring manifest (refs by import path), not a Graph — a Graph holds callables and can't be serialized; also the containment boundary making self-rewiring != self-coding | High |
| [0042](0042-owner-merge-is-the-promotion-gate.md) | The owner's review+merge to main is the promotion gate — strictly stronger than Phase-4 criterion 7; the evolution engine stays disabled | High |
| [0043](0043-separation-of-powers-is-inviolable.md) | A proposal may not modify the standard that judges it, in the same change (anti-reward-hacking); suites still evolve via standalone owner commits | High |
