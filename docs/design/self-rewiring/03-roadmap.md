> **⚠ REVISED — read `04-review-and-self-coding-redesign.md` first.** Three-reviewer
> audit disproved this document's premise (edges authorize routes; nodes choose them)
> and found the gate pipeline admitted only no-ops. Scope is now self-coding with a
> structurally isolated harness (ADR 0044). Retained for provenance.

# Self-rewiring agents — 03: roadmap

**Status:** planning artifact. No code accompanies this document.

Ordered milestones. Each has acceptance criteria that must be **true and
tested** before the next begins. Nothing merges to `main` without owner
approval; all work lands on `self-rewiring/<topic>` branches.

**Sequencing principle:** build the **judge before the judged**. Every
safety mechanism ships before the thing it constrains. A proposer is
worthless without gates, and dangerous without them.

---

## M0 — Reflection slice (prerequisite, already scoped)

**Why first:** the proposer is grounded in `failure`/`success` memory
(`01-architecture.md` §4.3), and nothing writes those records today
(gap G11; `reflection.py:23-39` are stubs).

**Scope:** the rule-based Critic/Judge slice already designed in
`docs/design/phase3-reflection-critic-judge-brainstorm.md` — `critic`/
`judge` slots on `Services`, `RuleBasedCritic`/`RuleBasedJudge` grounded
only in recorded signals, a `reflect_node` writing `MemoryRecord(kind=
"failure"|"success")`.

**Acceptance:** a real `GraphExecutor` run produces failure/success memory
records queryable via `MemoryStore.query()`; adversarial `AEFState`
fixtures covered; green bar; ADR.

**Independently valuable:** yes — this is real self-improvement (learn into
memory) even if the program stops here.

---

## M1 — Trace serializer + golden corpus substrate

**Why now:** G2 is the backbone gate and cannot exist without persisted
scenarios. Today no trace serializer exists — `Context` has no serializer
and `END` has no JSON form (gap G4, `contracts.py:104-131, 159-174`).

**Scope:** `NodeExecutionRecord` ⇄ JSON codec (including `Context`, the
`END` sentinel, and `Route`); a corpus directory format; a recorder that
promotes a real run into a scenario; the `services_fixture` mechanism for
pinning model/clock/tool non-determinism (G2 §2.3).

**Acceptance:**
- Every recorded scenario survives write → read → re-execute with identical
  results (the round-trip test).
- Two re-executions of the same scenario are byte-identical (determinism —
  else every downstream gate flakes).
- Never-shrinks CI assertion in place and demonstrated failing on a removal.
- Green bar; ADR for the trace format.

**Risk addressed:** R6 (a flaky corpus makes every gate unreliable).

---

## M2 — Wiring manifest + loader + `WiringDiff`

**Why now:** this is the artifact everything else operates on, and it
resolves gaps G1/G2/G3/G10.

**Scope:** manifest schema; loader (refs → `Graph` through the untouched
`compile()`); `Graph` → manifest extraction for the incumbent; the palette
registry; structured, serializable `WiringDiff` with modified-pairing and
**order** sensitivity (`GraphDiff` misses both — `00-current-state.md` §2).

**Acceptance:**
- A manifest loads to a `Graph` structurally equal to the equivalent
  hand-built one.
- Round-trip: `Graph` → manifest → `Graph` is stable.
- `WiringDiff` detects edge reorder and field-level modifications that
  `GraphDiff` cannot; serializes and renders human-readably.
- The shipped `examples/hello_agent` graph is expressible as a manifest
  (proof against a real graph, not a toy).
- Green bar; ADR for manifest-as-the-artifact.

---

## M3 — Gates G0, G1, G4 (the cheap, high-value ones)

**Why now:** these three are inexpensive, and **G4 must exist before any
proposer does** — it is the anti-reward-hacking rule.

**Scope:** palette+scope check; load+compile with the added reachability /
END-reachability assertions; separation-of-powers path/field allowlist.

**Acceptance:** every "how this gate is tested" case in each gate's spec
passes, **including the known-bad cases** (a gate that can't reject is not a
gate). G4's ordering test proves it runs before G2. Green bar; ADRs where a
decision was load-bearing.

---

## M4 — Gate G2 (golden-scenario re-execution)

**Why now:** the backbone, and the most expensive to build correctly.
Depends on M1 (corpus) and M2 (candidate construction).

**Scope:** re-execution harness; the comparison policy (G2 §4); the
complementary replay check; the full-corpus report.

**Acceptance:**
- The **routing-change test**: flipping an edge priority so routing changes
  ⇒ gate fails, naming the divergent step. *This single test is the proof
  that the gate does what replay could not.*
- A no-op reorder of unrelated edges ⇒ passes (not over-sensitive).
- An unpinned clock ⇒ fails loudly rather than flaking.
- Green bar; ADR recording re-execution-not-replay.

---

## M5 — Evaluation suite + gate G3

**Why now:** requires the corpus (M1) and unblocks non-regression scoring.
Today there is **no suite abstraction** and `EvaluationRecord`s are never
persisted (gaps G7/G8).

**Scope:** suite runner over the shared corpus; `EvaluationRecord`
persistence + aggregation; incumbent score caching; the four G3 rejection
rules.

**Acceptance:** a candidate breaking one previously-passing scenario is
rejected **even if aggregate mean improves** (the zero-tolerance rule);
cost-blowup rejection works; suite determinism verified. Green bar; ADR.

---

## M6 — Archive + rollback

**Why now:** must exist before anything is ever accepted, so that anything
accepted can be undone.

**Scope:** immutable versioned manifest store (reusing
`_atomic_write_text`, `durability.py:34-61`); each version stored with its
validation report and diff; one-command `rollback(graph_id, version)`;
never-shrinks.

**Acceptance:** rollback restores an exact prior manifest that loads and
re-executes identically; archive survives a torn write (the ADR 0031
property); a rollback is itself an owner-visible change. Green bar; ADR.

**Note:** deliberately a **separate, non-evolution** archive — the
`ArchiveStore` ABC in `aef/evolution/` stays a disabled Phase-4 stub
(`engine.py:77-83`).

---

## M7 — Gate G5 (rate + drift)

**Scope:** baseline designation (owner-only); structural drift metric; rate
window; reporting on pass as well as fail.

**Acceptance:** the **criterion-5 test** — several individually-small
accepted changes accumulate past the drift budget ⇒ hard stop; A→B→A churn
nets zero drift but still consumes rate; agent-proposed rebaseline rejected
by G4. Green bar; ADR.

---

## M8 — `MutationProposer` (rule-based)

**Why last:** every gate that constrains it now exists. Building the
proposer earlier would mean running an unconstrained proposer, which is the
thing the whole design exists to prevent.

**Scope:** `Services` slot; rule-based/heuristic proposal generation
grounded in `EvaluationRecord`s + failure/success memory; `WiringCandidate`
with rationale and `grounded_in` citations; no-op rejection.

**Acceptance:** every candidate carries grounding citations (an ungrounded
proposal is not emitted); candidates flow through the full gate pipeline;
a deliberately-bad proposal is caught by the appropriate gate. Green bar;
ADR.

---

## M9 — Review surface + end-to-end

**Scope:** branch creation; manifest diff + validation report rendering
(what changed, why, which gates passed with what numbers, eval delta);
owner approve/reject path; archive-on-approval.

**Acceptance:** a full loop demonstrated on `examples/hello_agent` — run →
reflect → propose → gates → branch diff + report → owner approves →
archived, **and** a rejected candidate never reaches the branch. Green bar;
ADR.

**This is the first point at which the system is what the program set out
to build.**

---

## Deferred (explicitly, not forgotten)

| Item | Why deferred | Revisit when |
|---|---|---|
| **Null-hypothesis baseline** (criterion 2) | Costly (many extra corpus runs); v1 accepts the exposure | R1 materialises, or before scaling to many graphs — **the top candidate to pull forward** |
| **LLM-backed proposer** | Rule-based first proves the pipeline; an LLM proposer changes no gates but raises R3 | After M9 is stable |
| **Agent-authored node code** (Q1) | Crosses self-rewiring → self-coding; needs a separate safety design | Not on this roadmap by recommendation |
| **Shadow execution / canary** (criteria 1, 6) | Unnecessary: no unattended live promotion occurs — the owner's merge is the promotion gate | Only if auto-promotion is ever reconsidered |

---

## Open questions requiring owner input

Consolidated from all planning docs; **Q1–Q5 block M2–M8.**

| # | Question | Recommendation |
|---|---|---|
| Q1 | May a proposer add node functions that don't exist (self-coding)? | **No for v1** |
| Q2 | Null-hypothesis baseline required in v1? | **Defer**, accept R1 exposure knowingly |
| Q3 | K (mutation rate) and window length? | Owner decision; start conservative |
| Q4 | Forbid removing an existing `requires_human_approval` flag outright? | **Forbid** |
| Q5 | Manifests in the adopted repo or aef-core? | **Adopted repo**; aef-core ships machinery |
| Q-G2-1 | Model-response keying strictness | **Strict** in v1 |
| Q-G2-2 | Significant-key declaration vs inference | **Declared per-scenario** |
| Q-G2-3 | Corpus wall-clock budget; behaviour when exceeded | Never silently truncate |
| Q-G3-1/2/3 | Tolerances, latency gating, incumbent cache invalidation | Report latency, don't gate |
| Q-G4-1 | Can any `domain_gate` read a proposer-writable param? | **Audit and close** |
| Q-G4-2 | Does an owner suite change invalidate in-flight candidates? | **Yes** |
| Q-G5-1/2/3 | K, drift metric weights, per-graph vs global | Per-graph with global report |
| Q-R1 | Accept R1 residual for v1? | Explicit owner decision |
| Q-R4 | Cadence for corpus-relevance review | Scheduled, not ad hoc |
| Q-R6 | Higher bar for gate code (mutation testing)? | Worth it for G2/G4 |

---

## Recommended first build milestone

**M0 — the reflection slice.**

Rationale: it is a genuine prerequisite (the proposer needs failure/success
memory to be grounded in), it is **already fully scoped**, it is small, it
carries no self-rewiring risk whatsoever, and it delivers standalone value —
agents that learn from their runs — even if the owner later decides not to
proceed to M1+. It is the lowest-risk way to start moving while Q1–Q5 are
being decided.
