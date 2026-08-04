# G4 — Separation of powers

**Inviolable.** This gate is the anti-reward-hacking rule. It is stated in
the program's control model as non-negotiable, and this document treats it
as such: no configuration flag disables it, and no proposal may modify it.

---

## 1. The rule

> **A proposal may not modify the standard by which it is judged, in the
> same change.**

Concretely, a `WiringCandidate` is rejected if its diff touches **any** of:

| Protected asset | Why |
|---|---|
| The golden-scenario corpus (any file under the corpus directory) | G2's evidence base |
| The eval suite: `domain_gates` definitions, the gate functions they reference, evaluator configuration | G3's scoring standard |
| The gate pipeline itself, including this document's rule and any gate's thresholds | The judge |
| `deterministic` / `side_effects` declarations on any node | Routes around replay enforcement and the idempotency contract (`contracts.py:204-210`) |
| Removal of an existing `requires_human_approval=True` edge flag | Removes a human safety gate (see Q4 in `../01-architecture.md`) |
| Anything under `aef/` | The kernel and its guarantees |

## 2. Why "in the same change" is the precise formulation

The corpus and eval suite **must** be able to evolve — a frozen test suite
rots (`../02-risks.md`). The rule is not "these never change"; it is
**"the entity proposing a behavioural change may not simultaneously change
the standard that judges it."**

So: an owner may absolutely add a scenario, retighten a gate, or retire a
stale case — in a **standalone, human-authored commit that carries no
wiring change**. That commit is reviewed on its own merits, where the
question "are we weakening our tests?" is the *only* question on the table
and cannot be smuggled in beside an attractive-looking improvement.

This is the same principle as separating the legislature from the judiciary,
and the same reason a developer shouldn't approve their own PR.

---

## 3. Exact definition

**Reject** iff the candidate's diff includes any path matching the
protected set (§1), **or** any manifest field in the owner-only list, **or**
the diff modifies a file the candidate's own validation run reads as
evidence.

**Owner-only field list** (expanded per 04 §1.9; canonical copy in
`../01-architecture.md` §2.2): `deterministic`, `side_effects`,
`idempotency_key_fn`, `fallback_node_id`, `requires_deterministic_fallback`,
and removal of any `requires_human_approval: true`.

**Accept** otherwise — G4 says nothing about the *quality* of a change,
only about its *scope*.

Implementation shape: a deterministic path/field allowlist check over the
candidate diff, run **before** the expensive gates (see
`README.md` ordering rationale) so a proposal that tries to edit its own
tests is rejected before it gets to run them.

---

## 4. Failure behaviour

- Auto-reject, **and flag loudly**. Unlike other gate failures — which are
  ordinary "this idea didn't work" outcomes — a G4 violation means the
  proposer attempted to alter its own judge. That is a category difference.
- The rejection is recorded with the offending paths/fields and surfaced in
  a **standing report to the owner**, even though the candidate itself is
  never surfaced. Repeated G4 violations are a halt-the-program signal
  (`../02-risks.md`).
- Nothing to roll back (no change applied).

---

## 5. How this gate could be gamed, and the mitigations

| Attack | Mitigation |
|---|---|
| **Split the attack across two proposals** — weaken the corpus in proposal A, exploit it in proposal B | The strongest attack against G4. Mitigations: (a) corpus/suite changes are owner-authored only, so proposal A cannot exist as an agent proposal at all; (b) G5's drift monitoring tracks cross-proposal accumulation; (c) any owner-authored suite change should invalidate in-flight candidates so they must re-validate against the new standard. |
| **Indirect edit**: change a manifest `params` value that a `domain_gate` reads, effectively moving the goalposts without touching the gate | Real and subtle. Mitigation: gates must be **pure functions of state**, not of proposer-controlled params; any `domain_gate` reading a proposer-writable value is a design bug to be caught in review. Flagged as **Q-G4-1**. |
| **Add a scenario that is trivially satisfied**, diluting the corpus | Agents cannot add scenarios at all (owner-only). Even so, G2 requires 100% pass, so dilution buys nothing. |
| **Propose a change to the gate ordering** so G4 runs after G2 | The gate pipeline is in the protected set (§1) and lives under `aef/`. |
| **Argue in the rationale** that a scenario is wrong and should be removed | Permitted and *desirable* — a proposer may **nominate** corpus changes in prose. The owner decides. Nomination is not modification. |

---

## 6. How this gate is tested

1. A candidate whose diff touches a corpus file ⇒ rejected, offending path
   named.
2. A candidate touching a `domain_gate` definition ⇒ rejected.
3. A candidate flipping `deterministic: false → true` ⇒ rejected.
4. A candidate removing `requires_human_approval: true` ⇒ rejected.
5. A candidate touching any path under `aef/` ⇒ rejected.
6. A pure wiring change (edges/priorities/params only) ⇒ **accepted** —
   proving the gate is not over-broad.
7. G4 runs **before** G2 in the pipeline ⇒ asserted by an ordering test, so
   a corpus-editing proposal never gets to execute the corpus.
8. A proposal that merely *mentions* a corpus concern in its rationale text
   ⇒ accepted (nomination ≠ modification).

---

## 7. Honest limitation

G4 is a **scope** control, not an **intent** control. It guarantees a
proposal cannot rewrite its own tests; it does not guarantee the proposal
is a good idea, nor that it isn't a subtly harmful change that passes every
automated gate. That residual is exactly why the owner's diff review is
load-bearing and is stated plainly in `../02-risks.md`.

---

## 8. Open questions

- **Q-G4-1** — audit whether any `domain_gate` can read a proposer-writable
  `params` value; if so, that path must be closed or the params field must
  become owner-only.
- **Q-G4-2** — should an owner-authored suite/corpus change automatically
  invalidate all in-flight candidates (forcing re-validation)?
  **Recommendation: yes.**
