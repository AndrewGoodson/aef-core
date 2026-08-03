# ADR 0014: `aef run --config` wires a real `model_provider`; full config-to-`Services` wiring is Phase 2 scope

## Status
Accepted

## Context
Auditing `aef/config/` for the same "declared but never consumed" pattern
(ADR 0010–0013) found something bigger than a single inert field:
`AgentConfig` — the whole per-agent config schema, loaded and validated
by `load_agent_config` — had **zero consumers**. Nothing anywhere turned
a validated `AgentConfig` into a wired `Services` container. `aef run`
(the CLI command that actually executes a graph) hardcoded
`InMemoryMemoryStore`/`InMemoryTracer`/`InMemoryDurabilityBackend` and
never set `model_provider` at all, config or no config.

This wasn't hypothetical: `aef run examples.hello_agent.graph
--objective "..."` — running this repo's own shipped example, the thing
`aef run` exists to do — failed outright with
`ServiceNotConfiguredError`, because `hello_agent`'s nodes call
`services.require_model_provider()` and nothing ever supplied one.

The natural fix — a general `build_services(config: AgentConfig) ->
Services` factory covering all six config sections — turns out not to be
honestly buildable today:
- `model_provider`: buildable. `AnthropicProvider` is real; `impl:
  anthropic` maps to it cleanly.
- `memory`: not buildable in general. `MemoryConfig` only carries `impl`
  and an optional `backend` string — nowhere near enough to construct a
  real `mem0.Memory()` (which needs an embedder choice, a vector-store
  choice, and an LLM configured; see ADR 0004). `impl: in_memory` is
  buildable; `impl: mem0` is not, without a much richer schema.
- `tools`: not buildable at all. `ToolsConfig.allow` is a list of scope
  name *strings*; there is no registry anywhere mapping a name like
  `"az_cli_ro"` to an actual `Tool` object. Building this requires the
  report's "Universal Plugin Architecture" (entry-point discovery) that
  doesn't exist yet.
- `policies`/`evaluator`/`knowledge_graph`: same shape of gap —
  `PoliciesConfig` maps cleanly to `PolicyConfig`/`PolicyEngine` (that one
  *could* be wired now) but `evaluator.suites` names evaluation suites
  that don't exist as loadable objects anywhere, and `knowledge_graph` has
  no backend to build against at all (ADR 0003).

Attempting a factory that only handles 2 of 6 sections and silently
no-ops the rest would repeat the exact mistake ADR 0010–0013 fixed:
a config field that looks consumed but mostly isn't.

## Decision
Scope the fix to what's honestly buildable today: `aef/config/factory.py`
exposes `build_model_provider(config: ModelProviderConfig) -> ModelProvider`,
handling `impl: anthropic` (including a `fallback` list, itself built
recursively — an unsupported fallback impl raises rather than being
silently dropped, same discipline as everything else this session).
`aef run` gained `--config PATH`: when given, it loads the `AgentConfig`
and wires a real `model_provider`; when omitted, `model_provider` stays
`None`, and a graph that needs one gets the existing, clear
`ServiceNotConfiguredError` rather than a silent no-op.

`memory`/`tools`/`policies`/`evaluator`/`knowledge_graph` remain
unwired, explicitly, with this ADR as the record of why: they need a
plugin-registry design (Phase 2, per the report's own "Universal Plugin
Architecture" framing) this repo doesn't have, not a quick dispatch
function.

A real bug surfaced and fixed along the way: the initial version of
`aef/config/factory.py` imported `AnthropicProvider` at module level,
which meant `import aef.config` transitively required the `anthropic`
package — an *optional* extra (`pip install ".[anthropic]"`) — breaking
`aef doctor`/`aef init` for anyone who installed aef-core without it.
Fixed by moving the import inside the function that actually needs it;
verified in a genuinely fresh venv built without the `anthropic` extra
installed, not just inferred from reading the code.

## Consequences
- `aef run --config <path>` now works for any graph whose nodes only need
  `model_provider` (plus the always-available in-memory
  memory/tracer/durability) — covers `hello_agent`'s failure mode and any
  similarly-scoped graph.
- A graph needing `memory.impl: mem0`, real `tools`, or `policies` from
  config still gets nothing from `--config` for those — `Services` fields
  for them stay at their defaults (`None`/empty), same as not passing
  `--config` at all. This is a known, explicit limitation, not a silent one.
- Building the full factory later is additive: `aef/config/factory.py`
  already establishes the per-section pattern (`build_X(config.section) ->
  RealThing`, raising clearly on unsupported values); a Phase 2
  `build_memory`/`build_policy_engine`/a real tool registry can follow the
  same shape.

## Alternatives Considered
- **Build a full `build_services(config) -> Services` now, accepting that
  most sections no-op.** Rejected: this is precisely the "field looks
  wired, mostly isn't" trap this session has spent its time closing, not
  opening a new instance of.
- **Leave `model_provider` unwired too, since the other five sections
  aren't ready.** Rejected: `model_provider` is fully, honestly buildable
  today and fixes a real, reproduced bug (`aef run` failing on this
  repo's own example) — deferring it to bundle with unrelated,
  not-yet-buildable work has no benefit.

## Confidence
High on the `model_provider` wiring — built, tested (including the
anthropic-import-isolation regression), and verified against the real
installed `aef` console script. High on the "don't half-build the rest"
reasoning; the report's own plugin-architecture section (§16) supports
treating that as real design work, not a quick pass.
