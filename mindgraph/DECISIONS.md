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

---

## 2026-08-05 · The legend is derived from the constants, never typed beside them

**Reproduced drift risk.** Section 4.2 requires the legend to print every
transform and cap. The caption did — as hardcoded text, while `contract.py`
held the real values. Two copies nobody compared, which is the class ADR 0091
names.

Demonstrated rather than argued: setting `RADIUS_K = 9.9` and rebuilding, the
derived legend now prints `6.0 + 9.9 x sqrt(...)`. Before, it would have kept
printing `3.4` while the renderer drew 9.9 — and a legend that lies is worse
than no legend, because it is believed.

The worked examples are also selected from edges that exist in the payload
(`162 traversals`, `57 traversals`, `0 observed`), so every number in the legend
is one the reader can find on the canvas.

---

## 2026-08-05 · A stale bytecode cache made a restore look like a failure

**Method hazard, and the third probe mistake tonight.**

After the drift test, `cp /tmp/contract.bak pipeline/contract.py` restored
`RADIUS_K = 3.4`, but the rebuilt page still printed 9.9. The source was
correct; the build was not.

Cause, confirmed by reading the `.pyc` header directly: Python validates its
bytecode cache on `(source mtime, source size)`. `3.4` and `9.9` are the same
byte length, and the restore landed in the same second as the edit — so both
fields matched and the stale bytecode was reused.

This is worth recording because it is silent, plausible-looking, and would have
produced a confident wrong conclusion in either direction: a drift test that
appears to fail when the code is right, or one that appears to pass when it is
wrong. `__pycache__` is gitignored, and drift probes clear it first.

---

## 2026-08-05 · `emit()` refuses a payload with no render blocks

**Reproduced by extending the verifier.** `_legend_text` crashed with
`KeyError: 'render'` on the escaping fixture, whose synthetic edges had no
render block.

Refused rather than tolerated. A `.get()` would have produced a page with a
legend containing no worked examples — quietly — which is exactly the bare
"brighter = more active" the report forbids. The verifier's fixture was also
wrong and now carries the render blocks the real contract always produces.

---

## 2026-08-05 · Persistence is proved by rendering, and the canvas is cropped

**Spec sets the threshold.** Stage 3 requires "zero coordinate drift between
two opens of the same artifact".

**Chosen.** Open the delivered file twice in headless Chrome from `file://`
with `NetworkService` disabled, and compare the canvas pixels.

**Why not reason about it.** Inspecting the drawing code would show that
today's code reads baked coordinates. It would not show that the page as
delivered puts the same marks in the same places — which is the actual claim.
Rendering it does.

**Why the canvas is cropped rather than comparing whole pages.** The header
stamp reports the file's own age from `Date.now()`, so it is *supposed* to
differ between opens. A whole-page comparison would be flaky in the worst
possible way: it would fail intermittently, and the failure would be the
staleness feature working correctly. The canvas carries the coordinates; the
stamp carries time; they are compared separately.

Proved by planting real drift into the DELIVERED page — `x + Date.now()%7` —
which produced 8802 differing pixels, then passed again on restore.

**This also closes a standing MANUAL_CHECK.** The offline headless load was
recorded as unautomatable because no browser had been confirmed present. One
was: `/Applications/Google Chrome.app`. Checking rather than assuming turned a
manual item into an automated one, which is worth remembering — the earlier
entry was honest but stale.

---

## 2026-08-05 · The birth tab is measured against `generated_at`, not `Date.now()`

**A real tension in the spec, resolved by its own words.** Section 4.3 requires
every visible age to be computed in the page so the file self-reports staleness.
Section 3d requires the birth tab to be "deterministic, screenshot-stable".
Applied naively, those conflict: an age computed from `Date.now()` ticks, so two
screenshots of the same artifact differ.

**Chosen.** Compute the tab at build time against the embedded `generated_at`,
and bake it in.

**Why that is not a violation of 4.3.** The two labels answer different
questions and neither loses. The tab says *how old the node was when this
picture was taken*; the header stamp says *how old this picture is*. A reader
with both knows when the node appeared, and nothing drifts. Computing the tab
live would also have failed 3.1's canvas pixel-stability check — for a reason
that is not a defect, which is the worst kind of test failure.

**Visibility is measured, not asserted.** Section 3d chose a tab over a halo
partly because a halo is invisible in a screenshot. So the verifier renders the
page twice, once with the tab suppressed, and counts the difference: 503 pixels
exist only because of the tab. Claiming "the tab is visible" without rendering
would have repeated exactly the mistake the verdict was correcting.

**Two refusals.** A `first_seen_at` after `generated_at` fails the build — a
negative age would render as a birthday in the future, and the clock
disagreement behind it is worth fixing at source rather than clamping. A node
never observed gets no tab: "NEW" over a node with no telemetry would be
inventing a birthday.

---

## 2026-08-05 · Staleness is proved by simulating the clock, not by reading the code

**Spec states the outcome.** Section 4.3: compute all visible ages from the
embedded values "so a file opened 3 days later *looks* 3 days stale".

**Chosen.** Override `Date.now` before the page script runs, render in headless
Chrome, and read the stamp out of the resulting DOM at +0, +3 and +30 days.

**Why.** The requirement is about what a reader sees on a future day, and no
amount of inspecting `age()` demonstrates that. The simulation does: the stamp
reads `3d ago` and `30d ago` respectively, and all three differ from each other.

The 3.2 rule is now also enforced structurally rather than by convention: the
page contains **exactly one** live clock read, and it is inside `age()`, which
only the header stamp uses. Every age describing a thing *in* the picture is
baked at build time. Both halves are asserted, so a future increment that
reaches for `Date.now()` in the canvas fails the check rather than quietly
breaking pixel stability.

---

## 2026-08-05 · `14.0-day` invents precision it does not have

Cosmetic, recorded because it is the same class as the numbers this project
cares about. The dormancy window is a configured integer; rendering it as a
float suggests the boundary was measured to one decimal place. Windows now
print as integers when they are integral.

---

## 2026-08-05 · The fleet is a LEFT JOIN, and the direction is the whole thesis

**Spec is emphatic; recorded because the wrong version is the easier one to
build.** Section 4.4: assemble the fleet from an authoritative registry and
left-join telemetry, never from whoever emitted data.

The failure mode is worth stating plainly. Build the list from emitters and a
repo that stops reporting **does not go red — it stops existing**. The page
looks calm, every row on it is green, and the one thing you needed to know is
the row that is not there. The failure removes its own evidence, which is the
cardinal anti-pattern in its most literal form.

So the registry is authoritative: every registered repo gets a row, always, and
absence of telemetry is a rendered state rather than a missing row.

**`error` is deliberately not `never`.** A collector that failed means we know
we *cannot see*; a repo that never reported means we *see nothing*. Conflating
them lets a broken exporter masquerade as a quiet agent, and those need
different people to fix them.

**The reverse case is a finding, not a filter.** Telemetry arriving for a repo
absent from the registry means the registry is stale — somebody stood up an
agent nobody recorded. It is surfaced as `unregistered` rather than dropped.

**Sorting encodes the requirement.** Non-reporting repos sort above healthy
ones, and within a state the longest-overdue sorts first, because the climbing
number is itself the signal and must be able to reach the top.

**Two absences kept as absences.** An empty registry is refused rather than
rendered as a calm empty fleet — a fleet page with no rows is indistinguishable
from a fleet with nothing wrong. And `oldest_overdue_seconds` is `None` rather
than `0` when nothing is overdue, because a zero would read as "the oldest
overdue report is 0 seconds old", a measurement of a thing that does not exist.

---

## 2026-08-05 · The exception queue is defined by what it excludes

**Spec is explicit and the reason is worth restating.** Section 4.4: the queue
is for rollbacks, gate errors, stale reporting, long-pending decisions and
abnormal collapse or surge — **not** ordinary rejections.

Most candidates are rejected. That is the designed behaviour of a system whose
job is to reject things. A queue that listed them would be long, boring and
permanently full, so the operator would learn to skip it — and the next
genuinely abnormal thing would be sitting in a list nobody reads. The panel's
value is entirely in its exclusions.

So the exclusion is explicit (`ROUTINE_OUTCOMES`) rather than an accident of
which branches happened to be checked, and **the page states it**: "not listed,
because these are the gate working as designed", followed by the names. An
empty queue is only trustworthy if the reader can see what it chose not to
list; otherwise "no exceptions" is indistinguishable from "nothing was checked".

**Out-of-band cuts both ways, and that is the subtle half.** A routine
rejection is never abnormal *because it was rejected* — but the RATE moving is
a different claim. A collapse to 1% means the gate stopped rejecting; a surge to
100% means the generator broke. Both are flagged, and both were verified.

**Two stated numbers rather than discovered ones.** "Long-pending" has no figure
in the report, so a 24h default is chosen and PRINTED on the page. An awaiting
gate with no `pending_since` is raised regardless — not knowing how long a human
has been blocking the loop is itself worth attention.

**One named gap.** Repeated proposal loops need per-proposal identity across
cycles, which the available data does not carry. Listed as undetectable rather
than approximated by something that would resemble it.

---

## 2026-08-05 · Reusing a class name broke five unrelated checks

**Reproduced regression, and the fix belonged at the source.**

The queue's footnote was rendered as `<p class="caption">`. The legend was
already `<p class="caption">`, and the verifier located it by splitting on that
string — so the footnote, appearing earlier in the document, silently became
the element five legend checks were reading. All five failed at once.

The tempting fix is to make the test cleverer: search all captions, or take the
last match. That would leave the ambiguity in place for the next element that
wants the class. The legend now has a stable `id`, and the checks target that.

A selector that was unambiguous when written is not unambiguous forever; the
fix is to make the thing identifiable, not to teach the test to guess.

---

## 2026-08-05 · CONSORT, not a funnel — and the palette must not smuggle the funnel back

**Spec adjudicates it (§3b, verdict B) and the reasoning is the design.** A
funnel's grammar says *wider top is success, everything leaking out is loss*.
Here that is not merely unhelpful, it is backwards: a rejected proposal is the
gate doing its job, so a funnel would draw the system working correctly as a
system leaking.

CONSORT treats every exclusion as an expected, counted, reason-annotated
branch. Nothing leaks; proposals arrive and are accounted for.

**The subtle half is colour.** Removing the funnel's shape but colouring
rejections red would re-import its claim through the palette. So in-band
rejection branches are neutral, and red is reserved for a rollback or a rate
outside its own historical band — the second being a statement about the RATE,
not about the rejections it counts. Both directions are asserted.

**Every proposal is accounted for, and the zero is shown.** Branches plus
unclassified must equal the cohort; a remainder is surfaced rather than absorbed
into rounding. The unclassified row renders **even at zero**, because a hidden
zero is indistinguishable from a figure nobody computed.

**A branch with no expected range reads `unknown`, not `in`.** It has not been
compared to anything, and reporting it as within expectations would be a claim
nobody made.

---

## 2026-08-05 · A pixel check silently started measuring an empty region

**Reproduced regression in the VERIFIER, not the artifact.**

Inserting the cohort flow above the canvas pushed the birth tab below the
1400px screenshot viewport. The tab-visibility diff then compared two identical
crops of empty space and reported **0 pixels**.

It failed rather than passed, which is the right direction — but the mechanism
is exactly this project's cardinal failure aimed at its own verifier: a check
that quietly stops measuring anything while still appearing to run.

Fixed at the root rather than by nudging the number. The capture size is now
decided in one place (`_shot_args`, 3200px tall) so no future panel can push
content out of frame, and the crop offset is generous rather than tight. Two
call sites previously carried their own duplicate window-size arguments; they
now share one.

---

## 2026-08-05 · Bands, not control charts — because there is no series

**Spec asks for Shewhart charts (§4.4). The data does not support them.**

A Shewhart chart's value is entirely in its run rules — points outside the
limits, runs on one side of the centre line, trends — and every one of those is
a statement about a *sequence*. The record carries per-window counts and
expected ranges and no series at all. Checked rather than assumed: the fixture's
only numeric arrays are the `expected_range` pairs, which are bands.

**Chosen.** Build the half the data supports, name the half it does not, and
say on the page which is which.

**Why that is not a cop-out.** The report's own worked example is a
single-point comparison:

> 90% rejection is healthy if the band is 88-93%; a sudden 55% means the gate
> stopped; 99.9% means the generator broke.

That judgement needs one observation and one band. It reproduces exactly, and
is asserted as three checks.

**Why faking it would be worse than nothing.** A single observation drawn with
a trend line implies a history nobody recorded, and an operator would read
direction out of one point. The absence of a series is itself information: it
says nobody is keeping the sequence, which is a fixable gap, and drawing over
it would hide the fix. `no trend line is drawn anywhere` is a check.

**Four categories, all stated.** Six metrics have a band; two have a reading
with no baseline; two (`human decision latency`, `gate evaluation duration and
timeouts`) are not recorded at all. The unbanded ones render dashed and read
"no baseline" — never as passing — and the absent ones are listed with the
reason. A panel that silently omitted three of its seven named metrics would
read as a complete panel, which is the same failure as a green row over no data.

---

## 2026-08-05 · A freshness rail, because a timeline needs history the registry lacks

**Spec asks for two things per repo (§4.4 item 5); the data supports one.**

A "Grafana-style state-timeline" draws *duration as length* across a sequence of
states — and the lengths only mean anything because they sit side by side. The
registry carries one `last_report_at` per repo and no transitions. Checked, not
assumed: the only per-repo fields are `repo`, `telemetry`, `last_report_at` and
`telemetry_error`.

**Chosen.** Build the freshness rail — one segment, length = how long the repo
has held its *current* state — and state plainly that the multi-segment timeline
is not derivable. Same move as 4.4's missing series, for the same reason.

**Scaled across the fleet, not per row.** `marlin` at 7d13h renders at 100% and
the others near zero. Normalising each row to its own maximum would make every
bar full and flatten exactly the climb that is the signal.

**A repo that never reported gets NO bar.** Zero length would read as "held this
state for no time"; a full bar would invent a duration nobody measured. It gets
the broken outline and no score, which is what §4.4 asks for in words —
"NEVER REPORTED with no score" — and the payload carries `held_seconds: null`
rather than `0`.

---

## 2026-08-05 · "Loop vs human" is not a comparison, and the panel says so

**The record settles it.** `counterfactual_stored: false`, with a note reading
"the comparison cannot be made from this data". The loop's throughput is
measured; what the same changes would have cost a human editing directly was
never recorded.

**Chosen.** Render one side of a two-sided question, named as one side.

**Why the naming matters more than the number.** A panel titled "loop vs human"
showing a single figure answers a question it has no data for — and the reader
supplies the missing comparator from imagination, favourably. So the panel
carries **no ratio, no delta, no arrow and no second bar**, because each of
those renders a comparison in a place where no comparison exists. Checked
against the rendered panel, not the source: no comparative language, no
ratio-like text, and "no comparator recorded" present.

**OBSERVATIONAL is load-bearing.** A non-OBSERVATIONAL label fails the build,
and so does a missing counterfactual with no explanation. The label is a
statement about study design rather than a placeholder waiting for data: the
report is explicit that this stays observational "unless randomized or matched
on repo, size, subsystem, and risk", so even a stored comparator would yield an
adjusted association, not a causal claim.

**DORA, honestly.** Throughput (2.7 durable changes per review hour) is shown
beside change-fail rate (5.6% of merges rolled back). Both halves are loop-side,
so the pair is computable without a comparator — and throughput alone is the
number that flatters, which is exactly why the pairing exists.

---

## 2026-08-05 · Naming the temporal frame, and deriving mode availability

**Spec lists three modes (Stage 5); the page has always shown one.** Naming it
matters for a reason only visible once a second mode exists: a reader who does
not know which temporal frame they are looking at will assume the most
flattering one.

"This path is thick" means *it has carried a lot, ever* — not *it is carrying a
lot now*. Those read identically at a glance and answer opposite questions,
which is exactly why rail and core are separate channels. The page now says
which frame it is in: **accumulated present**, explicitly not a snapshot.

**Availability is checked, not assumed.** One layout-state file, overwritten
each build, so no prior topology exists. But every node carries `previous_x`/
`previous_y` — so *where a node moved* is answerable while *what was added or
removed* is not. The difference map declares precisely that asymmetry instead
of claiming either. A mode selector offering a mode that cannot be drawn is
worse than one offering fewer and saying why.

---

## 2026-08-05 · Motion is banned outright, not conditionally disabled

**Spec says respect `prefers-reduced-motion` (Stage 5).**

**Chosen.** Have no motion at all, and enforce that as a forbidden-token ban:
`transition:`, `animation:`, `@keyframes`, `requestAnimationFrame`,
`setInterval` — each with a planted fault in `--self-test`.

**Why the ban beats the media query.** A `prefers-reduced-motion` rule is a
promise the *next* element has to remember to keep; the first contributor who
adds a fade without a matching rule breaks it silently. Having nothing to
reduce satisfies the preference unconditionally, and it is checkable.

Confirmed before claiming it: zero transitions, zero keyframes, zero animation
frames, zero timers in the whole document. `text-transform` is typography, not
motion. The page states the guarantee in its own footer, which also covers
Stage 5's requirement that every static end-state be interpretable without
having watched a transition — there are none to have watched.

---

## 2026-08-05 · The difference map is not offered, and 5.1 had overclaimed

**Reproduced correction of my own previous increment.**

5.1 declared that because every node carries `previous_x`/`previous_y`, "where
a node MOVED" was answerable while additions and removals were not. 5.2 checked
the actual numbers and the first half was wrong.

When the topology is unchanged, `build.py` writes
`Placed(n, prev, prev, prev, prev, "carried")` — **previous is a copy of
current from the same build**, not a coordinate from an earlier version. All
seven nodes had a displacement of exactly 0.0. A diff drawn from that would
show "nothing moved", and a reader would conclude the layout is stable across
versions when no second version was ever compared.

**Carrying a previous field is not the same as having a prior version.** The
availability test is now displacement, not presence.

Proved in both directions with two real builds rather than by reading the
classifier: an unchanged rebuild yields 0 moved and the mode reports that
nothing has been compared; a genuine topology change yields 7 of 8 moved and
the mode reports displacement as answerable. So the map will offer itself the
moment the data supports it, and not before.

**No empty diff panel is rendered.** An empty diff is precisely the failure
this project keeps naming — absence rendered as a measurement — and it is the
more dangerous form, because "no changes" is a satisfying thing to read.

**A second defect, caught by 5.1's own check.** With no nodes at all, the new
message claimed every node's previous coordinate was a self-copy — but there
are no nodes to have any. Two different absences ("nodes exist but none moved"
and "there are no nodes") were conflated, and naming the wrong one sends the
reader to look for a comparison that was never possible. Now distinguished.

## 5.3 — the scrubber, and the sequence that is not the one it needs

**Decision: the timeline scrubber is NOT OFFERED, on two independent blockers.**

Either one alone is fatal, and they are stated separately on the page so that
removing one reason cannot make the mode look available.

1. **No retained sequence of wiring versions.** `topology.json` carries
   `layout_version` as a single scalar (`7`) and no history array; the layout
   state file is overwritten on every build. Verified by building twice: the
   file was byte-identical in length, `layout_version` unchanged, nothing
   appended. There is no earlier version to scrub back to.
2. **Staged transitions are motion, and motion is banned.** §3g specifies the
   GraphDiaries add/remove/persist treatment. `transition:`, `animation:`,
   `@keyframes`, `requestAnimationFrame` and `setInterval` are all forbidden
   tokens with planted faults (5.1). So §3g's scrubber cannot be drawn here
   *with or without* a sequence.

§3g already makes the scrubber SECONDARY and explicitly user-initiated, and
adjudicates the difference map as the primary surface for "what changed". Its
absence therefore costs less than 5.2's did.

### What checking the data first actually found

"There is no sequence" would have been FALSE, and stating it would have been
the same class of error 5.2 caught in 5.1. A sequence does exist: the event log
spans **3 monthly windows**, and the set of edges carrying traffic changes
across them — **3 → 5 → 5** distinct edges. The declared edge set (10) never
changed in any of them.

So the distinction is precise, and the page states it: **that is traffic over
time, not wiring over time.** A scrubber built on that axis would answer *"when
did this path go quiet"*, not *"what did the wiring look like at version 5"*.
Both are worth answering. Presenting the first while labelled as the second is
exactly the substitution this whole artifact exists to refuse — and it is the
mistake a later contributor is most likely to make, precisely because the
timestamps are right there and look sufficient.

It was not built. §3g asks for the versions scrubber; a traffic scrubber is a
different requirement, and inventing it here would be scope the spec never set.
Named, measured, and left for the owner to decide on.

### prefers-reduced-motion: proved, not asserted

§5 requires the page to respect `prefers-reduced-motion` and keep every static
end-state interpretable. With motion banned outright there is no transient
state, so the static end-state is the *only* state — in both preferences.

That claim is trivially satisfiable and therefore easy to fake, because **a
null result from a broken instrument is indistinguishable from a null result
from a true claim.** So the check proves the instrument bites first: a control
page built to change colour under `@media (prefers-reduced-motion: reduce)` is
rendered with and without Chrome's `--force-prefers-reduced-motion`. It differed
by **160000 pixels** — the whole 400×400 control. Only then is the artifact
measured: **0 differing pixels**.

Probed by pointing the harness at a nonexistent flag. The control failed and
the parity check reported `not measured — the control proved the flag inert`
rather than a comfortable pass.

### A probe found a real defect in this increment

Handed fabricated variance on a single window, `_scrubber_partial()` wrote:

> "a DIFFERENT sequence does exist: the event log spans **1 windows** and the
> set of edges carrying traffic changes across them"

One window is not a sequence. Two fixes, because one was not enough:

- `_scrubber_partial()` now refuses `window_count < 2` itself. The function that
  writes a claim is the one that must refuse it — delegating that upstream and
  hoping is how the first version failed.
- The verifier no longer measures the windows by calling
  `modes.traffic_windows()`. It parses `events.jsonl` directly with a separate
  implementation, because a check that shares its subject's code shares its
  bugs and agrees with itself. Both now agree at `[3, 5, 5]`, and that agreement
  means something.

## 6.1 — dual themes, and what "identical semantic ordering" actually constrains

**Decision: both themes already existed; the increment was the verification,
which had never been run.** `prefers-color-scheme` and the `:root[data-theme]`
overrides have been in the CSS since Stage 2. Nothing was added. What was
missing was any evidence that the second theme preserved meaning, and §3f's
clause — *identical semantic ordering, never auto-invert luminance meaning* —
is precisely the thing an unchecked palette gets wrong.

### Two channels, two different tests, because they are different kinds of channel

**Recency is ORDERED**, encoded as alpha over the ground. This is the one that
looked most likely to break, because on a dark ground the accent composites
*brighter* as recency approaches 1.0, and on a light ground it composites
*darker*. Opposite directions in absolute luminance — and that is correct, not
a bug. What must be identical is the direction in **salience**, and it is:

| recency | dark salience | light salience |
|---------|---------------|----------------|
| 0.00    | 0.017         | 0.161          |
| 0.25    | 0.073         | 0.354          |
| 0.50    | 0.174         | 0.511          |
| 0.75    | 0.326         | 0.634          |
| 1.00    | 0.536         | 0.727          |

Strictly increasing in both. The most recent edge is the most salient edge in
either polarity, which is what "do not invert the meaning" asks for. The alpha
formula is **read out of the artifact's own JS** by regex rather than restated
in the check, so a change to the renderer cannot leave this validating a
formula the page no longer uses.

**State is CATEGORICAL**, encoded as hue. There is no magnitude to preserve, so
what must survive is *identity*: `--bad` must still be the red one after the
swap. Worst measured drift across themes is **6.2°** (`--ok`). Probed by
turning the light theme's `--bad` green: drift 134.8°, check fired.

### What is deliberately NOT asserted, and why

Contrast-against-ground does **not** hold its ordering across themes:

```
dark : accent > ok > warn > stale > bad > muted
light: muted > stale > bad > accent > ok > warn
```

This was tempting to call a defect. It is not one, and calling it one would
have been inventing a requirement — the failure mode this loop has hit twice
already. Contrast-vs-ground is not a declared semantic channel for the state
colours; **hue is**. The design encodes severity categorically, consistently,
in both polarities, which is also what keeps it inside the ≤3 preattentive
variables budget. Asserting an order the design never claimed would have
manufactured a finding.

What *is* asserted instead is a **floor**: every state stays readable against
its own ground (dark min 5.03, light min 3.32, both above 3.0). A state that
vanishes into its background is not a state an operator can act on — and that
is a real requirement, not an invented one.

### The documented flag was wrong, and assuming it would have been silent

The loop prompt suggested `--force-dark-mode`. Probed against a control page:
**headless Chrome already defaults to DARK**, and `--force-dark-mode`,
`--force-prefers-color-scheme=light`, `--force-light-mode` and
`--disable-features=WebContentsForceDark` *all* left the control unchanged.

Taking the documented flag on trust would have produced two identical renders,
compared them, and passed — a green check measuring nothing. This is the same
lesson 5.3 recorded and the reason its harness proves the instrument bites
before trusting a null result. The flag that actually works is
`--blink-settings=preferredColorScheme=0` (dark) / `=1` (light), confirmed
against the control in both directions.

### A hole in my own check, found by reading its output

The first version of the palette parser matched only 6-digit hex, so it
silently dropped `--panel:#fff` and reported `9 light` tokens against `10
dark` while passing. No token under test was affected, so nothing failed — a
check that skips what it cannot parse reports on a subset while looking like it
reported on everything. Fixed to accept both hex forms and normalise; the
completeness assertion now covers surfaces as well as states.

## Post-DONE — owner request: theme switch, Tailwind, sans-only

Three changes asked for after the checklist closed. One had a genuine conflict
with a hard constraint and needed resolving rather than obeying literally.

### Tailwind without breaking "no external refs"

Tailwind's usual delivery is `<script src="https://cdn.tailwindcss.com">` or a
linked stylesheet. Both are external references, both are banned tokens here,
and the artifact's CSP would block them anyway. Rather than refuse the request
or break the constraint, Tailwind is **compiled locally and inlined**:

- `styles/input.css` is the Tailwind source.
- `tools/build-css` runs the Tailwind CLI and writes `styles/tailwind.css`.
- That file is **committed**, and `emit.py` inlines it verbatim.

`tools/build-css` is deliberately NOT wired into `pipeline/build.py`. Doing so
would put npm — and, on a cold cache, the network — on the critical path of the
one artifact whose entire value proposition is having no dependencies. The
Python build stays offline and pure; regenerating CSS is an explicit, separate
step. `_load_css()` raises rather than emitting a page without it, because an
unstyled document would still pass every structural check.

The compiled sheet is 18.7 KB, purged. `node_modules/` is git-ignored: it is
build-time tooling, and nothing from it ships.

**Two things Tailwind brought in that had to be removed, not tolerated:**

- A `.transition` utility. The extractor is a text scan and `emit.py` is half
  prose — it discusses the scrubber's *staged transitions* and the fleet's
  *state transitions* — so Tailwind emitted a motion utility for a page where
  motion is banned. Blocked with `@source not inline("transition")`.
- The default mono stack. Preflight points `code`/`kbd`/`samp`/`pre` at
  `--font-mono`. Cleared with `--font-mono: initial` plus an explicit
  `font-family: inherit`, so there is no monospace on the page to fall back to.

### The semantic layer stays custom properties

Tailwind consumes the palette through `@theme`, but the palette itself remains
CSS custom properties rather than `dark:` variants. Two reasons:

1. The canvas resolves colours via `css('--ink')` at draw time. A 2D context
   cannot see utility classes, so the tokens have to be custom properties
   regardless of what the DOM uses.
2. 6.1 verified that this exact layering preserves semantic ordering across
   polarities. Re-expressing it as `dark:` variants would duplicate every colour
   at every use site, which is precisely how the inversion 6.1 checks for gets
   reintroduced. One palette, verified once.

### The toggle, and the seam underneath it

The DOM restyles itself for free when `data-theme` changes. **The canvas does
not** — it read those properties at draw time and baked them into pixels. A
toggle that only sets the attribute yields a light page wrapped around a dark
graph, and every structural assertion still passes.

So the toggle calls `draw()`, and the test for it is a render comparison:
clicking into light must produce the same picture the OS preference produces.
Probed by deleting the redraw — `clicking the toggle changes what is drawn`
still **passed** (3.3M pixels changed, all of it chrome), while the canvas sat
27612 pixels out of date. A source grep would not have caught that; only
comparing the two routes into light did.

The toggle also introduced a second new risk: there are now two ways into each
polarity, the media query and the attribute. If their palettes diverged,
clicking "light" would give a different light than the environment does, and
6.1's guarantees would hold for only one path. Both are now asserted equal.

**It persists nothing.** Browser storage of every kind is banned, so the choice
lasts the life of the page. That is a consequence of the read-only constraint,
not an oversight, and the button's title says so rather than letting the reader
discover it on reload.

### Two defects this work exposed in the existing checks

- **A latent time bomb.** `a file opened 3 days later reports 3 days` asserted a
  literal string, which only held while the baked `generated_at` was under a day
  old. It began failing at midnight, on an artifact nobody had touched, because
  `generated_at` is fixed — that is what makes the build deterministic. Replaced
  with the real invariant: shifting the clock by N days moves the reported age
  by exactly N days. Exact (the fractional offset cancels), true whenever it
  runs, and a stronger claim than the string match, because it proves the page
  *derives* the age rather than printing a constant.
- **Nothing asserted the page had a width.** The port dropped `main`'s
  max-width and padding; content ran off the right edge of the viewport with all
  287 checks green. Caught by looking at a screenshot. Now measured: a band of
  untouched page ground must survive down both edges.

Also fixed: the palette parser located blocks by splitting on literal text,
which broke the moment the sheet was minified (`prefers-color-scheme:light`
lost its space, and Tailwind's `@theme` added more `:root{` blocks). It now
locates blocks by content. It crashed rather than silently measuring the wrong
palette — the right failure, the wrong method.

And, for the record, my own comment explaining that browser storage is banned
contained the word `localStorage`, which tripped the literal token scan. The
scanner was right.
