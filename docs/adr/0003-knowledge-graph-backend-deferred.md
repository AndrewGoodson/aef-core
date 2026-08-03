# ADR 0003: Knowledge-graph backend is deferred to Phase 2; default target is Neo4j/FalkorDB, not Apache AGE

## Status
Accepted (interface only; no backend implemented yet)

## Context
The report and blueprint disagree on which graph database AEF should
default to. The report's comparison targets Neo4j (enterprise/cloud,
richest GraphRAG ecosystem, RBAC/clustering) for cloud deployments and
FalkorDB (GraphBLAS + HNSW vector search, fastest reads in third-party
benchmarks) for latency-critical embedded use, and explicitly flags Kuzu
as archived (October 2025) — "avoid for new builds," a instruction this
build also received directly. The blueprint instead recommends Apache AGE
as the *default* embedded graph layer, on the argument that it reuses
PostgreSQL infrastructure the checkpoint store would already depend on
(under the blueprint's own Temporal/Postgres-tiered durability design —
see ADR 0001, which this build did not adopt).

Because ADR 0001 already rejected the Postgres-centric durability tier
that motivated AGE's "zero new infrastructure" argument, and because
Phase 0/1 has no knowledge-graph consumer at all (`GraphStore` is an
unimplemented interface — see `aef/services/kg/base.py`), there is no
concrete workload yet to decide this against.

## Decision
Do not implement any `GraphStore` backend in Phase 0/1. Keep `GraphStore`
as a pure interface (entities/relations with temporal validity windows,
per report §14 / blueprint Part 6) so a future adapter — whichever engine
is chosen — only has to satisfy that contract. Record the target decision
for Phase 2 planning purposes: **Neo4j** for enterprise/cloud deployments,
**FalkorDB** for latency-critical embedded deployments, **Kuzu excluded**
as archived. Apache AGE remains a legitimate reconsideration *only* if a
future Postgres-centric durability tier is adopted (i.e., if ADR 0001 is
later revisited) — this ADR does not permanently foreclose it, it just
declines to default to it given the current durability architecture.

## Consequences
- Phase 2 knowledge-graph work starts from a clean interface with no
  backend-specific technical debt to unwind.
- The Neo4j/FalkorDB target is unverified against this project's actual
  workload (no knowledge-graph consumer exists yet to benchmark against)
  — treat it as a starting hypothesis for Phase 2, not a locked-in choice.

## Alternatives Considered
- **Default to Apache AGE now, per the blueprint.** Rejected: its
  rationale (reuse the Postgres checkpoint store) doesn't apply given
  ADR 0001/0002's file/in-memory durability choice; adopting it would mean
  optimizing for infrastructure this build doesn't have.
- **Default to Kuzu (embedded, zero-ops).** Rejected outright — the
  report flags it as archived, and the build task explicitly names it as
  a package to avoid.
- **Pick a backend and implement it now, ahead of Phase 2.** Rejected as
  premature: no Phase 0/1 component consumes `GraphStore`, so any
  implementation now would be unverified against real usage.

## Confidence
Medium — the Neo4j/FalkorDB direction follows the report's own comparison
matrix, but neither has been validated against this project's actual
graph-memory access patterns, which don't exist yet.
