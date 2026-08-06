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

---

## 2026-08-05 · `is_unknown_node` keys on the FILL channel only

**Spec ambiguous on.** Section 4.1 says a null *health* field forces the
UNKNOWN construction, but a node has six channels and any of them can be null.

**Chosen.** Only `node.fill` — backed by `operational_state` — decides whether
the whole node is drawn unknown. Other channels resolve unknown independently
and are drawn that way individually.

**Why.** The spec says "a null *health* field", and health is `operational_state`.
A node can have a null `lifetime_execution_count` (so an unknown radius) and
still be a legitimately measured node with a broken counter — drawing the whole
thing as unknown would overstate the absence. Conversely a node whose
operational state is null cannot be drawn as anything else, whatever its other
fields say. The conservative reading is to make the health channel decisive and
let the rest degrade in place.

---

## 2026-08-05 · UNKNOWN_TREATMENT frozen after a reproduced defect

**Not a judgment call — a defect, recorded because the fix constrains later
stages.** The treatment was a plain dict handed out as the `value` of every
unresolved channel, so `resolved.value["fill"] = "solid"` silently changed the
treatment for every UNKNOWN produced afterwards. Reproduced: one mutation, and
a fresh resolution of an unrelated node reported `fill='solid'`.

That is the cardinal anti-pattern the report names — *everything looks
healthy* — reachable by accident from any renderer that thought it was working
on its own copy.

Frozen with `MappingProxyType`, and the backing dict's name deleted: the proxy
is a VIEW, so leaving `_UNKNOWN_TREATMENT` bound would have kept the write path
open under a different spelling. Two regression checks added to `tools/verify`.

**Constrains later stages:** renderers must copy before adorning. The contract
hands out a shared read-only treatment by design.

---

## 2026-08-05 · REQUIRED_VISUAL_PROPERTIES is transcribed, not derived

**Spec silent on.** Section 6 Stage 0 sets the threshold — "100% of node/edge
visual properties must have a named backing field or the build fails" — but not
where the list of required properties comes from.

**Chosen.** Transcribe it by hand from Sections 4.1 and 4.2, and compare the
implemented catalogue against it.

**Why.** Deriving the required list from the channels that happen to be
implemented makes the check tautological: it would report 100% coverage
whatever was built, including nothing. The list has to come from the spec so
that forgetting a channel is detectable. The cost is that the transcription can
drift from the report, which is why `assert_complete` also fails on a channel
the spec never named — drift is caught from both sides.

---

## 2026-08-05 · `node.shape` is declared a CONSTANT rather than omitted

**Spec ambiguous on.** Section 4.1 lists "Shape: circles only" among the node
channels, but a fixed shape encodes nothing and so has no backing field.

**Chosen.** A `CONSTANT_PROPERTIES` entry stating it encodes nothing, rather
than leaving it out of the catalogue.

**Why.** An omission and a decision look identical in a missing entry. Leaving
`node.shape` out would be indistinguishable from having forgotten it, and the
whole point of this stage is that absence must be explicit. `assert_complete`
also refuses a property declared both as a channel and as a constant, so the
two lists cannot quietly disagree.

---

## 2026-08-05 · pm4py considered and not used

**Spec offers it.** Section 6 Stage 1 says "optionally with pm4py DFG
discovery"; the reference table flags pm4py as **GPLv3** and advises being
deliberate about it.

**Chosen.** Hand-write the derivation in the standard library.

**Why.** It is about forty lines. Taking on a copyleft obligation for forty
lines is a poor trade, and the loop's own rule is to prefer boring. pm4py
remains the right tool if the derivation ever needs real process-mining
machinery — variant analysis, conformance checking — none of which this artifact
asks for.

---

## 2026-08-05 · Derivation takes three inputs, not one

**Spec implies it; worth stating because the obvious implementation is wrong.**

Deriving the traversal graph from the event log alone is the natural reading of
"derive the traversal graph", and it is fatal: an edge nobody has taken would
be indistinguishable from an edge that does not exist, so the never-observed
state — one of the four the report requires — could never be produced.

Section 4.2 defines "never observed" as *configured + valid telemetry + zero
count*. All three are therefore inputs: the event log, the declared topology,
and the coverage declaration.

Two consequences worth recording. `retired` is read only from an explicit
`retired_at`, because the report is emphatic that dead is never inferred from
inactivity — an edge that stopped firing is a fact about the agent, while an
edge someone switched off is a fact about a human decision, and inferring the
second from the first attributes an intention nobody had. And an uninstrumented
node reports `None`, never `0`: zero is a measurement, `None` is "we were not
looking", and only the second may become the UNKNOWN construction.

---

## 2026-08-05 · The derivation found two defects in the fixtures

Recorded because both were caught by refusing to be lenient, and the temptation
in each case was to loosen the classifier instead.

1. **An observed traversal with no declared edge.** The generated log took
   `classify -> human_gate`, which `topology.json` did not declare. `derive()`
   raised rather than drawing it — presenting unconfigured activity as part of
   the design would be exactly the false-causality trap the report warns raw
   DFGs fall into. Fixed by declaring the edge, which is what the log says is
   real.

2. **The `never_observed` state had no instance.** `topology.json` labelled
   `fetch_invoice -> human_gate` as the never-observed case while the event log
   actually took that path, so the derived output contained no example of it and
   every downstream assertion about it would have been vacuous. Fixed by
   rerouting the log — the old runs now go `fetch_invoice -> emit` — so the
   never-observed edge is one somebody configured and nothing has ever used.
