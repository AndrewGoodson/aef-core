# ADR 0008: OTel GenAI semantic-convention attribute keys are pinned as local constants, not imported from opentelemetry-semantic-conventions

## Status
Accepted

## Context
The report notes "as of 2026 most GenAI conventions are still
experimental," recommending `OTEL_SEMCONV_STABILITY_OPT_IN` dual-emission
during the transition period. In practice, the
`opentelemetry-semantic-conventions` package ships GenAI attribute names
under an explicitly *incubating* namespace
(`opentelemetry.semconv._incubating`) with no stability guarantee across
point releases. Constraint #5 requires every node execution to emit a
`gen_ai.*`-conventioned span from day one — this is foundational, ongoing
instrumentation, not a one-off integration.

## Decision
`aef/observability/semconv.py` defines the attribute keys AEF actually
uses (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.response.model`, etc.) as plain string constants, matching the
GenAI semconv spec as published at the time of writing, plus an `aef.*`
namespace for AEF-specific span attributes (node id, determinism flag,
checkpoint sequence) that aren't part of the upstream spec at all. Nothing
in `kernel/` or `observability/` imports the incubating package.

## Consequences
- Attribute *names* are stable across OTel SDK point releases — a
  dependency bump can't silently rename or remove an attribute key AEF's
  own tracing depends on.
- If/when the GenAI semconv package stabilizes, migrating means updating
  one file's string constants (and adding a real dependency), not
  reworking every span-emission call site.
- AEF's local copy of the spec can drift from upstream if the spec
  changes and nobody updates `semconv.py` — this is an accepted,
  explicit maintenance cost in exchange for today's stability.

## Alternatives Considered
- **Import the incubating package now.** Rejected: ties a foundational,
  every-node-execution code path to a package explicitly marked unstable,
  for a spec area the report itself flags as still in flux.
- **Invent AEF's own attribute names instead of following the GenAI
  spec's naming at all.** Rejected: would forfeit interoperability with
  GenAI-aware observability backends (Langfuse, Phoenix, etc.) for no
  benefit — the actual GenAI attribute *names* are stable even though the
  Python package exposing them as constants isn't.

## Confidence
High.
