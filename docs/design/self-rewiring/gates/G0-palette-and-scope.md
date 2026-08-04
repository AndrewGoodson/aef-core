# G0 — Palette and scope

The containment boundary that makes self-rewiring ≠ self-coding.

## 1. Exact definition

**Reject** iff the candidate manifest:

1. references an `fn`, `condition`, or `idempotency_key_fn` import ref that
   is **not in the palette** (the set of refs that already exist in the
   repo and have been human-reviewed);
2. modifies an **owner-only field** — the full list (expanded per 04 §1.9;
   this gate originally named only the first two and the
   `requires_human_approval` removal): `deterministic`, `side_effects`,
   `idempotency_key_fn`, `fallback_node_id`,
   `requires_deterministic_fallback`, or a removal of
   `requires_human_approval: true` (`../01-architecture.md` §2.2);
3. is not a valid manifest per the schema (unknown keys, wrong types).

**Accept** otherwise.

## 2. Why this exists

An agent that can introduce an arbitrary new import ref can cause arbitrary
new code to run. The palette restricts a proposal to **recombining
already-reviewed building blocks**. Adding a new node function remains an
ordinary human-authored code change on its own PR
(`../01-architecture.md` §2.3).

## 3. Failure behaviour

Auto-reject with the offending ref/field named. An out-of-palette ref is
reported distinctly from a schema error — the former may be a legitimate
signal that the agent *wants* a capability that doesn't exist, which is
useful input for the owner even though the proposal dies.

## 4. Gaming, and mitigations

| Attack | Mitigation |
|---|---|
| Reference a ref that exists but was never intended as a node (e.g. an internal helper) | Palette is an **explicit allowlist**, not "anything importable". Derived from a declared registry, not from `dir()`. |
| Point a ref at a dynamically-dispatching function that then does anything | The palette entry is reviewed once, by a human, like any other code. Same trust model as the rest of the repo. |
| Smuggle behaviour through `params` (e.g. a prompt that instructs a tool to do something new) | Real; params are proposer-writable by design. Bounded by `PolicyEngine` (deny-by-default, HITL) at tool-call time, which G0 does not weaken. Flagged in `../02-risks.md`. |

## 5. How this gate is tested

1. Manifest referencing a nonexistent ref ⇒ reject, ref named.
2. Manifest referencing a real-but-not-in-palette ref ⇒ reject.
3. Manifest flipping `deterministic` ⇒ reject.
4. Manifest removing `requires_human_approval: true` ⇒ reject.
5. Manifest with an unknown key ⇒ reject (schema).
6. Pure edge/priority/params change using only palette refs ⇒ **accept**.

## 6. Open question

- **Q-G0-1** — how the palette is declared and kept in sync with the code
  (an explicit registry file? a decorator?). Affects developer ergonomics
  in the adopted repo. **Recommendation: an explicit registry file, because
  it is itself reviewable and diffable.**
