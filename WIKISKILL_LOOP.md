# Loop prompt — WikiSkill consolidation layer for aef-core

Paste after `/loop`.

---

LOOP_PROMPT — build the WikiSkill-style knowledge-consolidation layer
(arXiv:2608.27454) into aef-core. One increment per iteration, then stop.

## What already got settled, so you do not re-derive it

WikiSkill separates three layers: raw execution experience, consolidated
knowledge (the "wiki"), and executable skills. In aef-core terms:

- **Raw experience EXISTS**: `make_reflect_node` writes
  `MemoryRecord(kind="failure"|"success")` per run (ADR 0046). Do not rebuild it.
- **The wiki is the missing middle**: nothing consolidates records across runs.
  `MemoryRetriever` (ADR 0101) serves raw records under
  `context_budget_tokens`. That retriever is the wiki's consumer.
- **The skills layer is OUT OF SCOPE.** Automated skill/graph updates are
  `aef/evolution/`, which is hard-disabled (constraint #7) pending evidence
  named in `docs/trust/promotion-trust-case.md`. This loop must not touch
  evolution enablement, must not add a bypass, and must not claim the wiki
  unblocks it. The wiki's shippable value is better retrieval, full stop.

Also settled: the repo pattern is **rule-based first, LLM later** — that is how
reflection itself shipped, and why it was testable against hand-built state.
Follow it. And per ADR 0101, a `NotImplementedError` stub that nothing needs is
a promise, not a feature — do not add an LLM consolidator interface unless the
same loop implements it.

## Standing constraints (repo law, not loop preference)

- Node contract: `(AEFState, Context, Services) -> tuple[StateDelta, Route]`;
  DI only; `deterministic` honest; non-pure ⇒ `idempotency_key_fn`.
- Vendor isolation: any LLM call for consolidation imports its SDK only under
  `aef/providers/` or `aef/services/*/adapters/`.
  `tests/test_vendor_isolation.py` will catch you; don't make it.
- Green bar before every commit:
  `pytest -q ; mypy --strict aef ; ruff check . ; ruff format --check aef tests examples`
  Test count grows or holds.
- reproduce-first: construct the case and RUN it. Assert patches applied.
  Verify any detector against a planted fault. Never weaken a control.
- Any capability this loop adds gets its CLAUDE.md "what's real vs stubbed"
  line updated **in the same commit** — that paragraph is audited against code.
- Prime directive: no agent-specific branches. Knowledge is one of the five
  allowed per-agent axes; the consolidation *mechanism* is shared.

## The increments. One per iteration. Each ends with a commit or a written kill.

**I0 — ADR first.** Write `docs/adr/0110-*` deciding: (a) the wiki is a service
under `aef/services/knowledge/` with the same base/in-memory/adapter split as
`aef/services/memory/`; (b) consolidation is rule-based first (dedupe, count,
recency-weight failure signals across runs into `KnowledgeEntry` rows), LLM
summarization only as a provider adapter and only if implemented in this loop;
(c) what the wiki explicitly does NOT do — no skill auto-update, no evolution
unblock, no per-agent branching. Cite arXiv:2608.27454 and its ablation (the
persistent wiki, not the skill updater, carried the result — that is why
shipping only the wiki is coherent). No code this increment.

**I1 — the store.** `KnowledgeEntry` dataclass + `KnowledgeStore` base +
in-memory implementation, mirroring `aef/services/memory/` structure. Tests:
round-trip, upsert-by-key semantics, eviction/versioning as decided in I0.
Checkpoint round-trip if entries touch `AEFState`.

**I2 — the consolidator.** Rule-based: takes N `MemoryRecord`s, emits/updates
`KnowledgeEntry`s (recurring failure signatures, success patterns, counts,
last-seen). No LLM, no clock read except via injected time source, no vendor
SDK. Test against hand-built adversarial records: duplicates, contradictory
outcomes, one-off noise that must NOT become "knowledge". Planted-fault check:
a consolidator that emits an entry for a signal appearing once, when the ADR
threshold is ≥2, must fail its test.

**I3 — the wiring.** A contract-compliant node (or an explicit hook on the
reflect node — ADR decides which) that runs consolidation after reflection
writes. `side_effects="io"`, idempotency key from run id. Then extend
`MemoryRetriever` so consolidated entries compete with raw records under
`context_budget_tokens`, with the priority rule written in the ADR.

**I4 — the A/B eval.** Skill-creator method: same task corpus retrieved twice —
raw-records-only vs wiki-enabled — through the existing eval harness. Read the
retrievals, not just scores. If the wiki does not measurably improve what fits
in budget, **say so and write the kill**; a consolidation layer that loses to
`tail -n` on raw records is not worth its surface area. That result is a
result, not a failure.

**I5 — only if I4 survives.** LLM-backed consolidator as a provider adapter
(summarize clustered records → entry text), evaluated the same A/B way against
the rule-based one. If not reached this loop, the ADR records it as future
work by name — it does NOT get a stub interface.

## Each iteration

1. Read the ADR trail and the previous increment's commit first.
2. State the increment's expectation before running anything.
3. Build, run, measure. Green bar. Commit small with conventional message.
4. Append expectation/measurement/verdict to `WIKISKILL_LOG.md`.
5. Stop. One increment per iteration.
