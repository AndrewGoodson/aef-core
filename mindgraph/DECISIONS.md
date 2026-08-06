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

---

## 2026-08-05 · blake2b instead of the builtin `hash()` for perimeter placement

**Spec silent on.** Section 6 Stage 1 says "perimeter by hash of stable ID"
without saying which hash.

**Chosen.** `blake2b`, from the standard library.

**Why, demonstrated rather than assumed.** Python salts string hashing per
process by default. Two processes were run and asked for `hash("retry_guard")`:

```
-6126072786797140866
-260026301298584743
```

So `hash()` would place the same node somewhere different on every build —
exactly the non-determinism this module exists to eliminate, arriving through a
function that looks pure and has no obvious RNG in it. `blake2b` is stable
across processes, platforms and versions.

---

## 2026-08-05 · Fixed iteration count rather than convergence

**Spec silent on.** It calls for "bounded relaxation" without a stopping rule.

**Chosen.** A fixed `ITERATIONS` count.

**Why.** A convergence test ("stop when total movement < epsilon") has a result
that can depend on floating-point summation order, which is a difference that
survives into the coordinates and therefore into the committed artifact. A
fixed count is boring, reproducible and testable, and the layout quality
difference at this graph size is not observable.

---

## 2026-08-05 · Non-finite carried positions refused, not sanitised

**Reproduced defect, recorded because the choice between refusing and
repairing was a real one.**

An infinite or NaN carried coordinate propagated through the simulation and
would have been serialised by `json.dumps` as a bare `Infinity`/`NaN` — not
valid JSON, so `JSON.parse` throws and the entire page renders empty from one
coordinate. This is the same failure class as ADR 0108's D2 in the host repo.

Refused at the boundary rather than clamped to something sensible, because a
silently corrected position is a position the operator cannot trust: the node
would appear somewhere plausible, having come from a value that meant nothing.

---

## 2026-08-05 · Layout is recomputed when the topology changes, not when a build runs

**Reproduced defect. Recorded because the naive reading of "bounded relaxation
each build" is what produced it.**

Building twice over unchanged inputs moved all seven nodes. Relaxation was
applied on every build, so each run seeded from the previous run's output and
drifted a little further. Each individual step was inside the displacement
budget, so nothing failed — the map just decayed, permanently, for no reason.

The fix is a semantic one, not a tolerance one: an unchanged node set means
there is nothing to accommodate, so carried coordinates are returned verbatim
and no simulation runs. `layout_version` likewise bumps only when the topology
changes — versioning the build count would make "which version of the map am I
looking at" meaningless, and the report states the displacement budget *per
layout version*.

Clamping harder would have hidden this. The drift was legal under the budget;
it was the unconditional recomputation that was wrong.

---

## 2026-08-05 · Timestamps are inputs, never read from the clock

**Spec silent on.** Section 4.3 requires `generated_at` and `data_through` to be
embedded; it does not say where the pipeline gets them.

**Chosen.** Both are parameters, and `build.py` refuses a naive datetime.

**Why.** A pipeline that stamps `datetime.now()` produces a different artifact
on every run over identical data. That defeats the byte-stability the layout
state exists to provide, and it makes "did anything actually change?"
unanswerable from a diff — every build looks like a change. Naive timestamps
are refused because every visible age on the page is computed from these, and a
naive one means a different instant depending on where the page is opened.

---

## 2026-08-05 · The layout state file is separate from the artifact

**Spec silent on.** It says to carry `previous_x`/`previous_y` forward, not
where they live between builds.

**Chosen.** A `build/layout-state.json` the pipeline owns, distinct from the
delivered page.

**Why.** Reading coordinates back out of the rendered HTML would make the
artifact an input to its own generation: a corrupted or hand-edited page would
then silently rewrite the layout everyone else sees. The delivered file is a
snapshot of the positions it was built with; the state file is the pipeline's
memory. `build/` is gitignored — it is derived, and committing it would invite
someone to edit the memory directly.

---

## 2026-08-05 · The renderer-less page says so, rather than showing an empty canvas

**Spec silent on.** Stage 1.4 delivers the embedded payload; the renderer is
Stage 2. Nothing says what the page should look like in between.

**Chosen.** A visible notice stating that the data is complete and the renderer
arrives in Stage 2, plus a table of what the payload actually contains.

**Why.** An empty canvas is indistinguishable from a broken one. Shipping an
intermediate artifact that *looks* failed would train exactly the wrong
reflex in whoever opens it, and this project's whole thesis is that absence
must never be mistaken for something else — including the absence of a
renderer. The summary table also means the intermediate page is genuinely
useful: it shows node and edge counts by state, which is what you would check
first anyway.

---

## 2026-08-05 · Escaping is verified by round-trip, not only by absence

**Method note, recorded because the obvious test is insufficient.**

Checking that `</script><img` does not appear in the output proves the escaper
ran. It does not prove the escaper was correct: an over-aggressive one would
pass that check while mangling the payload, and the symptom — a blank page —
is identical to the symptom of no escaping at all.

So the check also parses the embedded blob back out and asserts the hostile
strings survive *as data*, byte-for-byte. Both properties are required and
neither implies the other.

---

## 2026-08-05 · d3-force is NOT vendored, and that is the resolution of 2.1

**Spec appears to require it.** Section 5(a)'s verdict is "hand-write the
renderer on Canvas and inline only d3-force (8.3 KB)".

**Chosen.** Do not vendor it. Ban runtime layout outright instead.

**This was a real decision, not a forced one.** d3-force was obtainable — a
local copy exists at `node_modules/d3-force/dist/d3-force.min.js` and the
network was reachable. The report's size claim was verified rather than
repeated: **8300 bytes minified, 3009 gzipped**, which matches "8.3 KB min"
and confirms the "~3 KB gzip" it had flagged as unverified.

**Why not vendor it.** The delivered page carries coordinates baked at
generation time and 774 characters of JavaScript, all of it computing
staleness. It runs no simulation and never will. d3-force would therefore be
8300 bytes of code nothing calls — the "declared thing with no caller" defect
class this loop has now caught four times, and the one that reads as a present
feature to anyone auditing the file.

**Where the report conflicts with itself, the adjudicated verdict wins.**
Section 5(a) recommends inlining d3-force because it assumes the page runs the
simulation. Section 3(a) — an explicitly adjudicated dispute, decided for
Report B — rules that coordinates are baked at generation time and there is no
runtime layout. The second is more specific, later, and reasoned; it governs.

**What replaced it is stronger than vendoring would have been.** Rather than
shipping a physics engine and trusting nobody calls it, the verifier now bans
the primitives outright in the delivered file: `forceSimulation`, `forceLink`,
`forceManyBody`, `velocityDecay`, `.tick(`. Each has a planted fault in
`--self-test`, so the ban is demonstrated rather than asserted. A future
contributor who reaches for a runtime layout fails the build instead of quietly
destroying the persistence property.

The physics still exists — in `pipeline/layout.py`, offline, in Python, already
verified deterministic and independent of input ordering. It is on the correct
side of the boundary.

---

## 2026-08-05 · The contract resolves at build time; the browser only draws

**Spec silent on.** Section 4.1 states the rule ("no visual property renders
unless its backing field is non-null") without saying where it is enforced.

**Chosen.** `pipeline/contract.py` resolves every node during the build and the
resulting construction is baked into the payload. The page reads
`node.render.construction` and branches on it.

**Why.** Enforcing in the browser would mean re-deriving health from fields at
view time, which puts a second implementation of the rule in a second language,
and the two would drift. Baking it means there is no code path in the delivered
file that could produce a healthy circle over an absent field — `fillFor()`
returns `null` by default rather than a colour, and the caller's only option
for `null` is the hatched construction.

---

## 2026-08-05 · `degraded` and `failed` are not derived, and that is the finding

**Reproduced gap.** Wiring the contract in made every node resolve UNKNOWN. The
contract was correct: `traversal.py` produced no health field at all, so there
was nothing to resolve.

`operational_state` is now derived as `normal` / `stale` / `never_executed`
from `last_seen_at` against the dormancy window. Those are what the event log
can honestly support.

`degraded` and `failed` — both named in Section 4.1 — are **not** derived,
because they require an error signal the event log does not carry. Inventing
that collection to make the picture look richer is forbidden, and would be the
exact move the report warns about. Their absence is reported rather than filled:
an adopter whose telemetry does carry errors can supply the field, and the
contract will resolve it without further change.

This is the second time the contract has caught the derivation rather than the
other way round, which is the layering working as intended.

---

## 2026-08-05 · `core_luminance` is null for never-fired, never 0.0

**Spec implies it; stated because the implementation naturally produces the
wrong thing.** Section 4.2 says core luminance encodes
`time_since_last_traversal`. For an edge that has never been traversed there is
no such time, and the obvious implementation — clamp to zero — makes
"never fired" render identically to "fired long ago".

**Chosen.** `null`, with the renderer drawing no core at all in that case, and
a strict `!== null` test rather than a falsy one.

**Why.** Those are different claims. An abandoned path is a *measurement*: the
agent used it and stopped, which is a fact about its behaviour worth seeing. A
never-taken path is an *absence*: nothing has happened there at all. A zero
would present the absence as the measurement.

Measured on the fixture: dormant renders a 4.86px rail with a dark core;
never-observed renders 1.00px with no core — a 4.9x width ratio, checked in the
verifier rather than eyeballed.

The falsy test is the specific trap: `if (core)` treats `0.0` and `null`
identically, so a correct data model would still have collapsed at the last
step. The check asserts on the strict comparison being present in the shipped
JS.

---

## 2026-08-05 · A test overwrote the artifact it was testing

**Reproduced regression, caught by reading the published page rather than the
verifier.**

`check_build`'s "add a node" test ran `pipeline/build.py` with `--state` and
`--out` pointed at temp paths, but not `--html` — which defaults to
`dist/index.html`. So every verifier run rebuilt the delivered artifact from a
synthetic topology, and the published page showed a `fraud_check` node that does
not exist in the fixture. The verifier stayed green throughout, because nothing
compared the artifact to the topology.

Two fixes, and the second matters more:

1. Every test build now passes an explicit `--html` to a temp path.
2. A new check asserts the delivered artifact contains **exactly** the declared
   nodes and edge count. Without it, the same class of contamination from any
   future test would again be invisible.

**On proving the guard.** The first attempt to plant the fault used
`subprocess.run(..., capture_output=True)` and the build never ran — so the
verifier reported PASS and I nearly recorded that as evidence the guard worked.
A planted fault that silently fails to execute is indistinguishable from a guard
that fires correctly. Re-run visibly, the guard failed as it should
(`extra=['fraud_check']`, 11 edges vs 10) and passed again once restored.

---

## 2026-08-05 · Each edge state gets a different KIND of mark, not a magnitude

**Spec gives the marks; recorded for the reasoning behind following it exactly.**

Section 4.2 assigns each state its own construction — dashed with open
endpoints, a perpendicular terminal cap, an alternating pattern with a midpoint
`?`. It would have been cheaper to lean on the rail width alone, which already
separates the states numerically.

That would be wrong for a reason worth stating: reading a width requires
comparing it against another edge in the same view. A reader who opens the page
and looks at one edge cannot tell whether 1.0px is thin without finding a 4.9px
one to hold it against. A dashed line with open rings is legible on its own.
Magnitude answers "how much"; kind answers "what is this" — and the states are
kinds.

---

## 2026-08-05 · An unrecognised gate disposition fails the build

**Spec silent on.** Section 4.2 lists five gate states and their glyphs. It does
not say what to do with a sixth.

**Chosen.** Raise, and refuse to produce an artifact.

**Why.** The alternatives are to draw nothing or to draw a generic mark. Drawing
nothing means an edge with a human checkpoint on it renders as an edge without
one — and the checkpoint is the single mark on this page that says traffic
stopped here for a person to decide. An operator who cannot see it will assume
the path is automatic. A generic mark is worse: it asserts a checkpoint exists
while hiding which way it went.

Verified by planting the fault visibly: a disposition of `probably_fine` fails
the build with the reason named.

---

## 2026-08-05 · An exit code is not evidence the intended check fired

**Method note, and the second instance tonight.**

The gate-disposition probe exited non-zero and I nearly recorded that as proof
the guard worked. It had failed on a stale layout-state file left by an earlier
probe — the disposition check never ran at all.

This is the same shape as the earlier `capture_output=True` mistake: a planted
fault that fails for an unrelated reason is indistinguishable from a guard
firing correctly, and both produce the output you were hoping to see. The rule
now applied to every probe: read the actual error text, not the exit status, and
confirm it names the check under test.
