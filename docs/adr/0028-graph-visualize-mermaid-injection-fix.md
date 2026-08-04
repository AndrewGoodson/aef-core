# ADR 0028: `Graph.visualize()` no longer lets a node id inject Mermaid syntax

## Status
Accepted

## Context
Adversarial pass on `aef/kernel/graph.py`'s `visualize()` — the third of
three areas swept this iteration alongside `otel_tracer.py` (ADR 0027) and
`aef/providers/` (came back clean). `visualize()`'s own docstring says its
output is "pasted straight into docs/PRs," so its job is specifically to
produce syntactically-valid Mermaid regardless of input.

Reproduced directly: a node id of `node"]; evil_injection --> pwned`,
passed through unchanged, produced

```
  node"]; evil_injection --> pwned["node"]; evil_injection --> pwned (entry)"]
```

— the node id was interpolated both as the raw (unquoted, unescaped)
Mermaid node identifier *and* inside a quoted label with no escaping. The
embedded `"]` closed the label early, and everything after it (`;
evil_injection --> pwned`) was no longer inert text — it became new,
independently-parsed Mermaid syntax appended to the same line. A node id
containing the right characters could inject arbitrary extra flowchart
statements into the diagram, not just render as a garbled label.

Node ids are declared in application code today, not derived from
untrusted runtime input, so this isn't currently reachable from an
external attacker — but it's still a genuine correctness bug independent
of exploitability: `visualize()`'s entire contract is "always produce
valid Mermaid," and it silently didn't for any node id containing `"`,
`]`, or a newline, benign or not (e.g. a node id someone legitimately
wanted to include a quote in for documentation purposes would already
corrupt the diagram).

## Decision
`visualize()` now assigns each node a synthetic, always-safe Mermaid
identifier (`n0`, `n1`, ... in `self.nodes` iteration order) used for both
the node's own declaration line and every edge line referencing it,
completely decoupling "what Mermaid parses as the graph identifier" from
any content in the real node id. The real node id (plus the `(entry)`
marker) is still shown as the node's **label** — quoted text, escaped via
a new `_mermaid_escape_label()` helper: `"` → `#quot;` (Mermaid decodes
this HTML-style entity back to a literal quote in rendered output, so the
label still displays correctly) and `\n`/`\r` → a space, since a
flowchart statement is one line and an embedded newline would otherwise
split it.

## Consequences
- The exact reproduction case (`node"]; evil_injection --> pwned`) now
  produces well-formed output: the malicious content is safely contained
  inside one label with no raw quote, and no extra statement is injected
  — confirmed the output is still exactly 4 lines (header + 2 node
  declarations + 1 edge) instead of a corrupted line plus an injected
  extra one.
- `visualize()`'s output format changed: edge/node lines now reference
  `n0`/`n1`/... instead of the raw node id as the Mermaid identifier. No
  other code in the repo consumes `visualize()`'s output programmatically
  (grepped `aef/`/`examples/` for callers — none), so this is safe;
  `test_visualize_produces_mermaid_flowchart` (the one existing test) was
  updated to match, and three new adversarial tests lock in the injection
  fix, newline handling, and node/edge id consistency.
- 284/284 tests (up from 281/281), mypy --strict clean, ruff clean.

## Alternatives Considered
- **Reject a node id containing dangerous characters at `Graph`
  construction/`validate()` time**, rather than making `visualize()`
  robust to any content. Rejected: node ids are a general-purpose string
  identifier used throughout the kernel (checkpoint file names, cursor
  values, trace lookups) — restricting their character set is a much
  bigger, unrelated behavior change for a bug that's specific to one
  output-formatting function. Making `visualize()` itself correct for
  arbitrary input is the narrower, correctly-scoped fix.
- **Only escape the label, keep the real node id as the Mermaid
  identifier when it happens to look safe.** Rejected: "looks safe" is
  exactly the kind of implicit trust this bug came from — a synthetic id
  is unconditionally correct with no character-set assumptions to
  maintain or get wrong later.

## Confidence
High — the exact injection was reproduced with a hand-built adversarial
node id before any fix existed, the fix was verified to produce
well-formed, correctly-structured output for that same input (not just
"no exception raised"), and the fix's behavior (synthetic ids, consistent
between node and edge lines, label escaping for both quotes and newlines)
was each independently asserted by a dedicated test.
