# ADR 0005: Default to single-agent-with-subagent-readers; deterministic hierarchical handoff, not emergent routing, when coordination is needed

## Status
Accepted (interface only; not wired into `GraphExecutor`)

## Context
The report's Key Finding #6 is unambiguous: multi-agent systems
outperform single-agent on read-heavy research tasks but "use about 15×
more tokens," and "token usage by itself explains 80% of the variance" on
one cited benchmark. It cites Cognition's argument that context
fragmentation makes parallel writers unreliable, recommending "multiple
readers, single-threaded writer" as the working pattern, and explicitly
states AEF's default should be "single-agent-with-subagent-readers,
escalating to full multi-agent only for parallelizable, read-heavy,
breadth-first work." The blueprint's Part 12 independently arrives at a
compatible position: "deterministic hierarchical handoff" as the default
coordination pattern for every regulated domain in scope, with emergent
(AutoGen-GroupChat-style) routing reserved as an explicitly opt-in, logged
exception — because non-deterministic routing is difficult to audit in
compliance-heavy domains (the report's own listed verticals: federal
contracting, healthcare, financial).

## Decision
No multi-agent orchestration is implemented in this repo. `aef/coordination/base.py`
defines `Coordinator`, `AgentRole`, and `HandoffRequest` as a Phase 5
interface only, with `HandoffRequest.input_filter_applied` a required field
— every handoff must declare that it applied a filter, directly
addressing the report's cited OpenAI Agents SDK failure mode (handoffs
default to passing the *entire* transcript, causing context bleed unless
explicitly filtered). When Phase 5 coordination is eventually implemented,
the default `Coordinator` should be a deterministic hierarchical handoff
implementation; emergent/conversational routing should ship later, if at
all, as an explicitly opt-in mode requiring the caller to log why
determinism was waived (mirroring `Edge.requires_deterministic_fallback`
in the kernel's own edge contract).

## Consequences
- Nothing in this repo currently spends the "~15× tokens" multi-agent
  tax — every example and every Phase 0/1 backend runs single-agent.
- A future agent author reaching for `aef/coordination/` will find a typed
  contract to implement against, but no working orchestration to
  configure — this is a deliberate scope boundary, not an oversight.

## Alternatives Considered
- **Implement a basic supervisor/worker `Coordinator` now.** Rejected:
  not in Phase 0/1 scope, and building it before any real multi-agent
  workload exists risks encoding untested assumptions into the interface
  itself.
- **Default to emergent/conversational routing for flexibility.**
  Rejected outright — both source documents converge on this being the
  wrong default for AEF's target domains (security, financial, federal
  contracting) specifically because of auditability requirements.

## Confidence
High — both source documents independently reach the same conclusion by
different arguments (token economics vs. auditability), which is a
stronger signal than either alone.
