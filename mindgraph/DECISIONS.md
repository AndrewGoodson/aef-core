# DECISIONS

Append-only. One entry per judgment call where the spec was silent or
ambiguous: what was chosen, and why it is the conservative option.

---

## 2026-08-05 · Project root is `mindgraph/`, not the repo root

**Spec silent on.** The loop prompt assumes `RESEARCH_REPORT.md`,
`LOOP_STATE.md`, `pipeline/`, `dist/`, `fixtures/` and `tools/` sit at the repo
root.

**Chosen.** A dedicated `mindgraph/` subdirectory of `aef-core`.

**Why.** `aef-core` is a Python scaffold with a documented layout contract in
its own `CLAUDE.md` — `aef/`, `tests/`, `docs/adr/`, and a rule that vendor SDK
imports live only in specific packages. Dropping a `dist/` and a `pipeline/` at
its root would violate the host repo's conventions, which are a hard constraint
of that repo even though the spec does not mention them. Every path in the loop
prompt is relative to a project root, so nothing else changes. The conservative
reading is: satisfy both contracts rather than break the one that was already
there.

---

## 2026-08-05 · `dist/index.html` check is left RED rather than stage-gated

**Spec ambiguous on.** Step 5 requires the verifier to check the delivered
file. At initialization nothing is built, so that check cannot pass.

**Chosen.** Leave it failing and report the failure, rather than making the
check conditional on the current stage.

**Why.** The loop prompt is explicit that "a red verifier is useful output" and
that honesty about failure beats progress theatre. A stage-gated check would go
green because nothing had been built, which is the same shape as the cardinal
anti-pattern the report names — absence rendering as health. The verifier
should say the artifact is missing, because it is.

---

## 2026-08-05 · Verifier ships with `--self-test`

**Spec silent on.** Step 5 lists the checks the verifier must implement, not
whether the verifier itself is checked.

**Chosen.** A `--self-test` mode that plants each forbidden token and asserts
the scan fires, plus an inverse case asserting a clean document produces no
finding.

**Why.** A scanner that cannot detect is not a scanner. The planted faults use
the REAL tokens (`Math.random`, `</script>`-adjacent `src="https:`, and so on)
rather than paraphrases, because a paraphrased fault is how a detector passes
its own check and is still wrong. The inverse case matters equally: a scanner
that flags everything would pass all fourteen positive cases and be useless.

Result at initialization: 14/14 planted faults detected, no false positive.

---

## 2026-08-05 · Fixture asserts the dormant/never-observed distinction on the DATA

**Spec silent on.** Step 2 requires the fixture to contain both cases; step 5
requires the rendered result to distinguish them.

**Chosen.** Also assert, in the verifier, that the two are separable *in the
fixture data itself* — dormant has `lifetime_traversal_count > 0`,
never-observed has `count == 0` and `last_traversal_at == null`.

**Why.** If the fixture ever loses that distinction, every downstream assertion
about the rendering becomes vacuously true and the verifier would go green on a
dataset that cannot exercise the rule. Checking the precondition is cheap and
the failure mode it prevents is silent.

---

## 2026-08-05 · Inherited from the host repo, recorded here for traceability

The `<button>` question that blocked the previous program is settled by this
spec's Hard Constraints, which ban `<form` and say nothing about `<button`. The
host repo's forbidden list was replaced accordingly (ADR 0108) — not trimmed —
and the replacement is stricter: it adds `sessionStorage`, `indexedDB`,
external `src`/`href`/`@import`/`url(http…)` references, and `Math.random`.

`Math.random` immediately caught a live violation in the host repo's existing
renderer, where edge particle phases were randomly seeded, so identical data
drew a different picture on every load — quietly incompatible with the
persisted-layout requirement this spec makes central.
