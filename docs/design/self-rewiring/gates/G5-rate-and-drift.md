# G5 — Rate and drift budget

The gate that thinks in **sequences of changes**, not single changes. It
carries Phase-4 criteria 4 (bounded mutation rate) and 5 (cumulative-drift
monitoring) into this program (`engine.py:21-25`).

## 1. Why a per-change gate set is insufficient

Every other gate judges one candidate in isolation. But the documented
failure mode (criterion 5, `engine.py:23-25`) is precisely the one that
**no single-change gate can see**:

> Several individually-compliant edits accumulate into a later regression.

Each change passes G0–G4 honestly. The tenth change lands the system
somewhere no one chose. G5 exists to make accumulated change visible and
bounded.

## 2. Exact definition

**Reject** iff:

1. **Rate** — the number of accepted wiring changes for this graph within
   the trailing window exceeds **K** (owner-configured; see Q3 in
   `../01-architecture.md`).
2. **Drift** — the cumulative diff between the **current** manifest and the
   **last owner-designated baseline** exceeds a drift budget, measured as a
   structural distance (count of changed edges/nodes/params, weighted).

**Accept** otherwise, and always **report** current rate and drift usage
even on pass, so the owner sees the trend before it hits a limit.

## 3. Baselines and resets

A **baseline** is a manifest version the owner explicitly blesses as "this
is the known-good shape." Drift is measured from the baseline, not from the
immediately-previous version — otherwise drift resets to zero on every
accepted change and measures nothing.

Rebaselining is an owner action (it implicitly asserts "I have reviewed
where we've ended up and I accept it"). It cannot be proposed by an agent.

## 4. Failure behaviour

- **Rate exceeded:** the candidate is not rejected on merit — it is
  **deferred**. Report says "rate budget exhausted; next window opens at
  T." This distinction matters: the idea may be good, the pace is the
  problem.
- **Drift exceeded:** hard stop until the owner either rebaselines or
  reverts. This is a deliberate "come look at this" trigger.

## 5. Gaming, and mitigations

| Attack | Mitigation |
|---|---|
| **Bundle many changes into one proposal** to stay under the rate limit | Drift is measured structurally, not per-proposal, so a large bundle consumes proportionally more drift budget. Also, a huge diff is exactly what an owner review catches. |
| **Split one change into many trivial ones** to stay under the drift budget | The rate limit bounds this from the other side. The two limits are deliberately complementary: rate caps frequency, drift caps magnitude. |
| **Propose a rebaseline** to reset the budget | Rebaselining is owner-only (§3), in the G4 protected set. |
| **Churn**: repeatedly change a value back and forth to consume rate budget harmlessly while masking a real change | Drift is computed against the baseline, so A→B→A nets to zero drift; the rate limit still counts the churn, which surfaces in the report as anomalous activity. |

## 6. How this gate is tested

1. K+1 accepted changes in a window ⇒ the K+1th is deferred, with the
   window-open time reported.
2. Changes within budget ⇒ accepted, with usage reported.
3. Drift accumulating past the budget across several individually-small
   accepted changes ⇒ hard stop. *This is the criterion-5 test and the
   reason the gate exists.*
4. A→B→A churn ⇒ drift returns to zero; rate still counts 2.
5. Owner rebaseline ⇒ drift resets to zero.
6. An agent-proposed rebaseline ⇒ rejected by G4.

## 7. Open questions

- **Q-G5-1** — the value of K and the window length (owner decision, Q3).
- **Q-G5-2** — the drift distance metric and its weights (is a changed edge
  condition worth more than a changed `priority`? almost certainly yes).
- **Q-G5-3** — should drift budget be per-graph or global across all graphs
  in a repo? **Recommendation: per-graph, with a global report.**
