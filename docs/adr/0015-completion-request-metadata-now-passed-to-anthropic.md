# ADR 0015: `CompletionRequest.metadata` is now passed through to Anthropic's own `metadata.user_id`

## Status
Accepted

## Context
Continuing the field audit into `aef/providers/`: `CompletionRequest.metadata:
dict[str, str]` is declared on the vendor-neutral interface, but
`AnthropicProvider.complete()` never read it — every request silently
dropped whatever a node put in `metadata`. The real `anthropic` SDK's
`messages.create()` does accept a `metadata` parameter (confirmed via
`inspect.signature`), shaped as `{"user_id": Optional[str]}` — used for
Anthropic's own abuse-detection tracking. So this wasn't a hypothetical
gap: a node passing `metadata={"user_id": "..."}` to help Anthropic
correlate abusive traffic to an end user had that intent silently
discarded.

Unlike `Edge.requires_human_approval` (ADR 0011) or `ToolCall.tool_name`
(ADR 0012), this isn't safety-relevant — it's a translation-layer
completeness gap. `FallbackProvider` (`aef/providers/base.py`) was
audited alongside it and found already correct: it already only catches
`ModelProviderError` (a genuine adapter bug — anything else — correctly
propagates immediately rather than being silently retried against the
next provider), already tries every provider in order until one succeeds,
and already includes every failed provider's name and reason in the
aggregate error. That coverage simply wasn't locked in by a test before
this pass.

## Decision
`AnthropicProvider.complete()` now extracts `request.metadata.get("user_id")`
and passes `metadata={"user_id": ...}` to the SDK call when present,
`None` otherwise (matching the existing `system` parameter's None-when-absent
pattern). Every other key in `request.metadata` is deliberately ignored for
this specific adapter — `CompletionRequest.metadata` is vendor-neutral by
design (a future OpenAI/Gemini adapter might use different keys for its
own vendor-specific tracking), so "Anthropic only understands `user_id`"
is a fact about Anthropic, not a bug in the interface.

Added regression tests for `FallbackProvider`'s already-correct behavior
that had no test coverage: trying a third provider after two failures,
the aggregate error naming every failed provider (not just the first),
and — the one genuinely load-bearing gap in test coverage — that a
non-`ModelProviderError` exception (an adapter bug) propagates
immediately rather than being caught and silently retried.

## Consequences
- Any node that already constructs `CompletionRequest(metadata={"user_id":
  ...}, ...)` gets real behavior for the first time, with no code change
  needed on the node's side — the fix is entirely inside the adapter.
- Nodes using metadata keys other than `user_id` against
  `AnthropicProvider` specifically will still see those keys dropped —
  expected, not a residual bug, since Anthropic's API has no slot for them.

## Alternatives Considered
- **Raise if `request.metadata` contains unsupported keys.** Rejected:
  would make the vendor-neutral interface leak vendor-specific
  restrictions back onto every caller, defeating the point of having
  `ModelProvider` be vendor-neutral at all — a node targeting multiple
  providers via `FallbackProvider` shouldn't have to know which metadata
  keys each one accepts.

## Confidence
High — directly confirmed via the real SDK's own type signature, not
inferred from documentation, and the fix is small, tested, and additive
(no existing caller's behavior changes, since none previously set
`user_id` and had it silently work).
