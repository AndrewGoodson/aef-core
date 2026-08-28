# WikiSkill loop — increment log

Append-only. Expectation stated BEFORE the work, measurement after, verdict last.

---

## I0 — ADR first (2026-08-28)

**Branch:** `wikiskill/knowledge-layer`, off `main` (`f945a72`).

**Expectation.** A design decision only, no code. Four things had to be pinned
or the later increments would each re-litigate them: where the wiki lives, what
keys an entry, when consolidation runs, and how entries compete with raw records
under one budget. Expected the ADR to be writable without touching `aef/`, and
the green bar therefore to be unchanged.

**Measurement.**

```
pytest -q                                 1455 passed, 0 failed
mypy aef                                  Success: no issues found in 108 source files
ruff check .                              All checks passed
ruff format --check aef tests examples    195 files already formatted
```

Baseline test count for this program: **1455**. It grows or holds; it never
silently shrinks.

Four cited claims were verified against source rather than recalled:

- ADR 0046 title is literally "The reflection slice is rule-based" and rejects
  an LLM-backed Critic first — the rule-based-first precedent is real.
- ADR 0096:33 contains the "flaky node" argument verbatim, so the
  `failing_nodes` signature key rests on a written decision, not on my summary.
- `aef/evolution/engine.py` imports only stdlib today, so the "knowledge does
  not import evolution, evolution does not import knowledge" constraint starts
  true and is a property to preserve rather than one to establish.
- `MemoryRetriever` is deterministic by construction (no model, stable total
  sort) because replay asserts deterministic nodes reproduce — which is what
  forced the write-time-vs-retrieval-time decision.

**Verdict.** I0 done. ADR 0110 accepted, indexed in `docs/adr/README.md`.

The non-obvious decision, recorded because I2/I3 depend on it: **consolidation
runs at write time**, and not for speed. Replay re-executes deterministic nodes
and asserts output equality, so a consolidator invoked during retrieval could
never be LLM-backed without breaking replay for every node that retrieves.
Consolidating at write time makes the entry stored *data*, which is what keeps
I5 possible at all.

Also recorded: the layer has a defined kill. If I4's A/B shows consolidated
entries do not improve what fits inside `context_budget_tokens`, the layer is
deleted and 0110 is superseded with the number that killed it.

**Next:** I1 — `KnowledgeEntry` + `KnowledgeStore` base + in-memory
implementation, mirroring `aef/services/memory/`.
