# G3 — Eval non-regression

Where G2 asks *"did behaviour change?"*, G3 asks *"is it actually better,
or at least not worse?"*

## 1. The prerequisite that does not exist yet

`Evaluator.evaluate(state)` scores **exactly one completed `AEFState`**
(`eval/base.py:44-49`). There is **no suite abstraction**: no fixture
corpus, no expected-output pairing, no batch runner, no aggregation, and
`EvaluationRecord`s are **never persisted** (`../00-current-state.md` §6,
gaps G7/G8).

So G3 cannot be built on today's evaluator alone. It requires an
**evaluation suite**: a set of scenarios run through a graph, each
producing an `EvaluationRecord`, aggregated into a comparable summary.

**Design economy:** the golden-scenario corpus (G2) and the eval suite are
the *same scenario set* viewed two ways — G2 compares the *trace/final
state* to a golden record; G3 compares the *`EvaluationRecord`* to the
incumbent's. Build one corpus, run it once per candidate, feed both gates.
This is why G3's marginal cost is "moderate" and not "expensive".

## 2. Exact definition

Run the suite against **both** the incumbent graph and the candidate graph
(the incumbent's scores may be cached from its own acceptance run).

**Reject** iff any of:

1. **`passed` regression** — any scenario where the incumbent's
   `EvaluationRecord.passed` is `True` and the candidate's is `False`.
   `passed = task_completion >= 0.5 and all(domain_gates.values())`
   (`eval/base.py:41`, ADR 0038). This is the hard floor: **no scenario
   that used to pass may fail.**
2. **Aggregate regression** — mean `task_completion` across the suite is
   lower than the incumbent's beyond a tolerance.
3. **Domain-gate regression** — any individual `domain_gate` that held for
   the incumbent now fails for the candidate.
4. **Cost regression** — aggregate `cost_tokens` exceeds the incumbent's by
   more than a configured budget (`cost_dollars` is always `None` today,
   `rule_based.py:44-47`, so tokens are the only cost signal available).

**Accept** on beat-or-tie across all four.

## 3. Why "beat or tie" and not "must improve"

Many good rewirings are cost or clarity improvements that leave scores
flat. Requiring strict improvement would either block them or pressure the
proposer toward score-chasing — the exact behaviour that produces
overfitting. Tie is acceptable; regression is not.

## 4. Failure behaviour

Auto-reject with a per-scenario score table (incumbent vs candidate,
delta), so the failure is diagnosable and the next proposal is
better-informed. Nothing to roll back (no change applied).

## 5. Gaming, and mitigations

| Attack | Mitigation |
|---|---|
| **Overfit to the suite** — rewire so suite scores rise while real behaviour degrades | The central risk of any eval-gated system. The suite is a *sample*, not a specification. Partial mitigations: the suite grows over time; G2 independently requires behavioural equivalence; the owner reads the diff. Full mitigation requires a null-hypothesis baseline (criterion 2, deferred — `../02-risks.md`). |
| **Weaken a `domain_gate`** so it's easier to satisfy | G4 — the suite is in the protected set. |
| **Exploit the aggregate tolerance** — take many small regressions that each sit under the threshold | Rule 1 (`passed` regression) has **zero** tolerance, so no previously-passing scenario may fail regardless of aggregates. G5's drift monitoring tracks accumulation across proposals. |
| **Score improvement via cost blow-up** (better answers by spending 10× tokens) | Rule 4's explicit cost budget. |
| **Trivially-satisfiable new scenarios** | Agents cannot add scenarios (G4/owner-only). |

## 6. How this gate is tested

1. Candidate identical to incumbent ⇒ accept (tie).
2. Candidate that breaks one previously-passing scenario ⇒ reject (rule 1),
   even if aggregate mean improves. *This is the important test.*
3. Candidate that improves mean but fails a `domain_gate` ⇒ reject (rule 3).
4. Candidate that ties on scores but doubles `cost_tokens` ⇒ reject
   (rule 4).
5. Candidate that genuinely improves ⇒ accept, with the delta reported.
6. Suite determinism: two runs of the same graph over the same suite
   produce identical `EvaluationRecord`s (else the gate flakes) — shares
   the fixture machinery from G2 §2.3.

## 7. Open questions

- **Q-G3-1** — the aggregate tolerance and cost budget values.
- **Q-G3-2** — should `latency_ms` be a gate? It's environment-sensitive
  and would flake in CI. **Recommendation: report it, don't gate on it.**
- **Q-G3-3** — where are incumbent scores cached, and how are they
  invalidated when the suite changes? (Interacts with **Q-G4-2**.)
