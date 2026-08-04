# G2 — Golden-scenario re-execution

**The backbone gate.** This is the one that answers "did this rewiring
change what the agent actually does?"

---

## 1. Why this is re-execution, not replay

The program's original framing was "replay 100% of a never-shrinking
recorded-trace corpus." Grounding showed that **replay cannot detect a
wiring regression** (`../00-current-state.md` §3.1):

`ReplayEngine.replay()` walks the **recorded** trace, looking each node up
by id (`replay.py:47`) and re-executing only `deterministic` non-fallback
nodes to compare their output (`:52-72`). `_validate_chain` (`:80-110`)
checks the trace's *internal* consistency — that `record[i].route ==
record[i+1].node_id`. **Edges, conditions, and priorities are never
consulted.** Replay follows the path that was recorded; it never asks the
candidate graph where it *would* go.

> Consequence: rewire the edges however you like, and an old trace still
> replays clean. Replay validates node implementations, not wiring.

Therefore G2 is defined as **re-execution**: run each golden scenario's
recorded **initial state** through the **candidate** graph with a real
`GraphExecutor`, and compare the resulting trace and final state to the
golden record. Routing is genuinely exercised because `_resolve_route`
(`executor.py:233-260`) runs against the candidate's real edges.

Replay is retained as a **complementary** check (see §6) because it is the
only thing that catches a deterministic node whose *implementation* drifted.

---

## 2. The golden corpus

### 2.1 What a golden scenario is

```
scenario_id            stable, human-meaningful
initial_state          the AEFState a run started from
services_fixture       deterministic stand-ins for all non-deterministic
                       services (see §2.3)
golden_trace           the recorded NodeExecutionRecord sequence
golden_final_state     the AEFState the run ended in
golden_eval            the EvaluationRecord that run produced
recorded_at            provenance: graph version, manifest version, date
```

### 2.2 Recording

Scenarios are recorded from real runs via
`GraphExecutor.run(record_trace=True)` (`executor.py:133-143`), which is
the existing, unmodified mechanism. Curation is **human**: an owner
promotes a run into the corpus. Agents may *nominate* a scenario (e.g. "this
failure mode isn't covered") but **may not add, edit, or remove corpus
entries** — that is G4's rule and it is inviolable.

### 2.3 Determinism of the corpus (the hard part)

A scenario is only a regression test if re-execution is reproducible. Every
non-deterministic input must be pinned by the `services_fixture`:

- **Model calls** — a recorded/stubbed `ModelProvider` returning the exact
  responses from the golden run, keyed by request. A candidate that makes a
  *different* model call than the golden run gets a well-defined result: an
  explicit `UnexpectedModelCall` failure, which is itself signal (the
  wiring changed what gets asked).
- **Clock** — `Services.clock` is already injectable (`contracts.py:68`);
  pin it to the recorded timestamps.
- **Tools** — stubbed via the `Services.tools` mapping.
- **Memory/retrieval** — a fixed store seeded to the recorded contents.

**Open question (Q-G2-1):** how model responses are keyed when the
candidate issues a semantically-similar but not byte-identical request.
Strict keying maximises reproducibility and flags more changes as
"unexpected"; loose keying risks false passes. **Recommendation: strict in
v1** — a changed prompt *should* require an owner's eye.

### 2.4 Serialization (a real prerequisite)

The corpus must persist to disk, and today **no trace serializer exists**
(`../00-current-state.md` §4, G4). `AEFState`/`StateDelta` round-trip via
pydantic, but `Context` is a plain frozen dataclass with no serializer
(`contracts.py:104-131`) and `Route`'s `END` is a bare sentinel object
(`contracts.py:159-174`). Building a `NodeExecutionRecord` ⇄ JSON codec is
a named milestone, not an implementation detail.

### 2.5 The corpus never shrinks

Mirrors Phase-4 criterion 3 (`engine.py:18-20`). Enforcement:

- The corpus is a versioned directory in the repo; removals appear in the
  git diff and are therefore owner-visible.
- G4 rejects any *proposal* that touches it.
- A CI check asserts `len(corpus) >= len(corpus@main)` — a mechanical
  backstop that fails the build on any shrink.
- Owners may retire a scenario, but only in a standalone, human-authored
  commit that does not carry a wiring change (again: G4).

---

## 3. Exact definition

**Pass** iff, for **100%** of corpus scenarios, re-executing
`initial_state` through the candidate graph yields:

1. the **same final routing path** (sequence of `node_id`s), and
2. a **final state equivalent** under the comparison policy (§4), and
3. no new `errors` entries absent from the golden final state, and
4. no `RoutingViolationError` / `HumanApprovalRequiredError` /
   `GraphExecutionError` that the golden run did not also raise.

**Fail** on the first scenario that diverges — but the report lists **all**
divergences, not just the first (see §5).

---

## 4. Comparison policy (what counts as "the same")

Naïve full-state equality is too brittle (timestamps, run ids, token
counts). The policy compares:

| Compared strictly | Ignored | Compared with tolerance |
|---|---|---|
| routing path (node id sequence) | `run_id` | `cost_tokens` (±N%) |
| `plan.status` | `Provenance.ts` | `latency_ms` (not compared) |
| presence/absence of `errors` | `trace_id` | |
| `tool_results` error-ness (`.get("error")`, the de-facto convention, `rule_based.py:66`) | | |
| terminal `working_memory` keys the scenario declares as significant | unlisted scratch keys | |

**Open question (Q-G2-2):** whether "significant keys" are declared
per-scenario (precise, more curation work) or inferred (cheap, brittle).
**Recommendation: declared per-scenario.**

---

## 5. Failure behaviour

- Auto-reject; the candidate never reaches the owner.
- The rejection record names: scenario id, the first divergent super-step,
  golden vs actual routing path, and a diff of the compared fields.
- **All** scenarios are run even after the first failure (bounded by a
  wall-clock budget), because "this rewiring broke 14 scenarios" is a
  materially different signal from "it broke 1" — it tells the proposer's
  next iteration how bad the idea was.
- Nothing to roll back: no change has been applied (see `README.md`).

---

## 6. Complementary replay check

After re-execution passes, run `ReplayEngine.replay()` over each golden
trace against the candidate graph. This catches the orthogonal failure:
a `deterministic=True` node whose implementation changed such that it no
longer reproduces its recorded output (`replay.py:58-72`). Expect
`DeterminismViolationError` to be the signal. Note this is only meaningful
if node code changed — which a *pure wiring* proposal cannot do (§2.2 of the
architecture), so in v1 this check is a cheap invariant assertion rather
than a primary gate.

---

## 7. How this gate could be gamed, and the mitigations

| Attack | Mitigation |
|---|---|
| **Shrink or weaken the corpus** so fewer scenarios can fail | G4 (proposal may not touch the corpus) + the CI never-shrinks assertion + git-visible removals |
| **Add a trivially-passing scenario** to dilute the pass-rate signal | Pass requires **100%**, not a ratio — dilution buys nothing |
| **Overfit to the corpus**: rewire so corpus scenarios pass while general behaviour degrades | The deepest risk here; the corpus is a *sample*, not a specification. Partially mitigated by corpus growth and G3; fully addressed only by a null-hypothesis baseline (criterion 2, deferred — see `../02-risks.md`) |
| **Exploit loose comparison tolerances** (e.g. hide a cost blow-up inside the ±N% band) | Keep tolerances tight and explicit; log the actual deltas in the report so the owner sees drift even when it passes |
| **Make the corpus expensive** so it gets run less often | Corpus runtime is reported per candidate; a wall-clock budget with an explicit "scenarios skipped" line (never silent truncation) |

---

## 8. How this gate is tested

The gate is control-plane code and gets the same treatment as the rest of
the kernel:

1. **Known-good:** an unchanged manifest re-executes 100% of a small corpus
   and passes.
2. **Known-bad (routing):** flip an edge priority so routing changes ⇒ gate
   must fail, naming the divergent step. *This is the test that proves the
   gate does the thing replay could not.*
3. **Known-bad (condition):** swap a condition ref so a branch is taken
   differently ⇒ fail.
4. **No-op change:** reorder two unrelated edges of different priority ⇒
   pass (proves it isn't over-sensitive).
5. **Non-determinism leak:** a fixture that fails to pin the clock ⇒ the
   gate must fail loudly rather than flake.
6. **Corpus shrink:** removing a scenario ⇒ CI assertion fails.
7. **Serializer round-trip:** every corpus scenario survives
   write→read→re-execute with identical results.

---

## 9. Open questions

- **Q-G2-1** model-response keying strictness (§2.3).
- **Q-G2-2** significant-key declaration vs inference (§4).
- **Q-G2-3** wall-clock budget for a full corpus run, and what happens when
  the corpus outgrows it (parallelism? sampling? — sampling would weaken
  the 100% guarantee and needs an explicit owner decision).
