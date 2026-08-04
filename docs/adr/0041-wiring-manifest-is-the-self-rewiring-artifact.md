# ADR 0041: A declarative wiring manifest is the artifact agents rewire

## Status
Accepted (planning decision; no implementation yet)

## Context
The self-rewiring program requires agents to propose changes to their own
graph wiring as artifacts that can be diffed, archived, reviewed by the
owner, and rolled back.

A `Graph` cannot serve as that artifact. `Node.fn`, `Edge.condition`, and
`idempotency_key_fn` are Python callables (`aef/kernel/contracts.py:192-229`),
so a `Graph` cannot be serialized. There is no `to_dict`/`from_dict` on
`Graph`/`Node`/`Edge` anywhere in the kernel, and no declarative graph
specification or loader exists — graphs come into being only imperatively,
via a module's `build_graph()` (`aef/cli/run.py:67-70, 83`).

`Graph.diff()` (`graph.py:76-92`) compares two *live* graphs but is not a
sufficient substitute: its `GraphDiff` holds `Edge` objects containing
callables (unpersistable), it detects node changes only by `version`-string
inequality, it misses edge **declaration-order** changes even though order
is the documented tie-break for equal-priority edges (`graph.py:63-70`),
and it has no modified-pairing concept.

## Decision
A graph's **wiring** is expressed as a declarative **manifest** — YAML/JSON
that describes nodes, edges, conditions, priorities, and tunable params,
and references code **by import path** rather than embedding it. A
**loader** resolves those refs into real `Node`/`Edge` objects and
constructs a `Graph`, which then goes through the existing, unmodified
`Graph.compile()`/`validate()` path.

The manifest — not the live `Graph` — is what proposers modify, archives
store, diffs render, and the owner reviews. A structured `WiringDiff`
between two manifests (order-sensitive, with field-level modified-pairing)
is the diff currency, replacing `GraphDiff` for this purpose.

## Consequences
- Resolves the blocking gaps at once: a serializable artifact makes the
  archive (G9), the structured diff (G10/G3), and the review surface
  possible.
- **It is a containment boundary, not merely a format.** A proposal may
  only reference import refs that already exist and have already been
  human-reviewed. An agent can *recombine* vetted building blocks; it
  **cannot author new behaviour**. Self-rewiring is therefore not
  self-coding — the single most important safety property of the design.
- The owner's review becomes tractable: a manifest diff ("edge
  `draft→search`: priority 10→0, condition `needs_search`→`always`") is
  legible in seconds, where an arbitrary Python diff would not be.
- Cost: a manifest schema, loader, palette registry, and `Graph`→manifest
  extraction must be built and kept faithful to the imperative path. The
  round-trip (`Graph` → manifest → `Graph` structurally equal) is a
  required test, not a nicety.
- The kernel is unchanged. Hand-authored `build_graph()` graphs keep
  working; manifests are an additional front door, not a replacement.

## Alternatives Considered
- **Make `Graph` serializable** (e.g. register callables in a global
  registry keyed by name). Rejected: it is the manifest idea with worse
  ergonomics — the registry *is* a palette, but embedded in the kernel,
  changing kernel types for a feature that lives above them.
- **Have agents emit Python code for `build_graph()` directly.** Rejected
  outright: it erases the containment boundary and turns every proposal
  into arbitrary code that must be code-reviewed rather than
  wiring-reviewed. This is the self-coding line the program deliberately
  does not cross (see `docs/design/self-rewiring/01-architecture.md` Q1).
- **Use `GraphDiff` as the diff currency.** Rejected: unpersistable, and it
  misses edge reorder and unversioned node changes — both of which are real
  behavioural changes.

## Confidence
High on the decision. The serialization blocker was verified directly in
the source, and the containment property is a genuine safety gain
independent of the format question. Medium on the schema's specific shape —
the illustrative manifest in the architecture doc is a sketch, and the real
schema will be settled in milestone M2 against `examples/hello_agent`.
