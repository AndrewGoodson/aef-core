STATUS: DONE (plus one post-DONE owner request, verified — see LAST_RUN)
STAGE: COMPLETE — all six stages verified; only the two on-hardware operator tests remain, and they are owner-blocked
CHECKLIST:
- [x] init.scaffold — pipeline/ dist/ fixtures/ tools/ created; RESEARCH_REPORT.md installed
- [x] init.fixtures — synthetic dataset covering every required edge case (fixtures/fleet.json)
- [x] init.verifier — tools/verify created, self-test passes on 14 planted faults
- [x] 0.1 — encoding contract as CODE: a validator that refuses to emit a visual property when its backing field is null, and forces the UNKNOWN construction (hatched interior, broken border, "?")
- [x] 0.2 — build fails unless 100% of node/edge visual properties have a named backing field (report §6 Stage 0 threshold)
- [x] 1.1 — pipeline: derive traversal graph from the event log
- [x] 1.2 — pipeline: offline layout, deterministic seeding only (weighted centroid of positioned neighbours; perimeter by hash of stable ID; never Math.random)
- [x] 1.3 — pipeline: carry previous_x/previous_y forward; bounded relaxation within a hard displacement budget of ~1 node diameter per layout version; store layout_reason
- [x] 1.4 — pipeline: embed graph + positions + history + generated_at + data_through + expected interval in a <script type="application/json"> block
- [x] 2.1 — d3-force NOT vendored, and that is the resolution: the delivered file runs no simulation, so it would be 8300 bytes of dead code. Replaced by a permanent ban on runtime-layout primitives (see DECISIONS.md)
- [x] 2.2 — hand-written Canvas renderer: node channels per §4.1 (position/radius/fill/border/interior glyph/birth flag; ≤3 preattentive variables; no glow, ever)
- [x] 2.3 — two-layer edge model per §4.2: history rail width = log1p(lifetime_traversal_count), activity core luminance = recency
- [x] 2.4 — the five endpoint states, each visually distinct: never-observed / dormant / retired / unknown / stale
- [x] 2.5 — mid-edge gate glyph as a RECTANGLE (§3c verdict B), states [H…] [H✓] [H✗] [H!] [H↶]
- [x] 2.6 — legend with concrete worked examples, windows, numbers, and every log/sqrt transform and cap printed
- [x] 3.1 — persistence: a file reopened later renders pixel-identical node positions (threshold: zero coordinate drift between two opens)
- [x] 3.2 — birth-flag tab ("NEW"/"3h"/"2d") computed from now − first_seen_at against embedded generated_at; static, not a halo (§3d verdict B)
- [x] 3.3 — staleness self-display: all visible ages computed from embedded timestamps; never labelled LIVE
- [x] 4.1 — dashboard: registry LEFT-JOIN telemetry; coverage + freshness strip first
- [x] 4.2 — dashboard: exception queue (rollbacks, gate-eval errors, stale reporting, long-pending decisions) — NOT ordinary rejections
- [x] 4.3 — dashboard: CONSORT-style cohort flow, neutral colours for expected rejection branches, red only for operationally abnormal (§3b verdict B)
- [x] 4.4 — dashboard: stability BANDS (not control charts — no series exists; see DECISIONS.md) beneath the flow
- [x] 4.5 — fleet table with FRESHNESS RAILS (state-timeline needs history the registry lacks; see DECISIONS.md); stale repos float to TOP; never retain a last green fill as dominant after reporting stops
- [x] 4.6 — loop-vs-human panel labelled OBSERVATIONAL; disclose that the direct-human-edit counterfactual is not stored
- [x] 5.1 — temporal mode 1: default accumulated present, NAMED, with the other two modes stating what they would need
- [x] 5.2 — difference map NOT OFFERED: nothing has been compared. Detector in place so it becomes available the moment a build actually relaxes (see DECISIONS.md), two synced panes (primary "what changed")
- [x] 5.3 — scrubber NOT OFFERED, on two independent blockers (no retained wiring-version sequence; staged transitions are motion, banned). A traffic-window sequence DOES exist and is named as a different question, not repurposed. prefers-reduced-motion verified by rendering both preferences against a control page that proves the flag bites (see DECISIONS.md)
- [x] 6.1 — dual themes VERIFIED (both already existed since Stage 2; the increment was the check, which had never run). Ordered channel (recency->salience) monotone in BOTH polarities; categorical channel (state->hue) drifts at most 6.2deg; contrast floor held on both grounds; page proven to respond to the preference by rendering, against a control page proving the browser can switch
- [ ] 6.2 — MANUAL: on-hardware polarity A/B (light vs dark) for "find the abandoned path" and "find the missing-reporting node"
- [ ] 6.3 — MANUAL: comparison-mode A/B (difference-map vs two-pane vs scrubber) measured on error rate and time, not FPS
NEXT: nothing automatable remains. 6.2 and 6.3 are on-hardware operator task-tests and are OWNER-BLOCKED — see BLOCKERS.
BLOCKERS: 6.2 and 6.3 only, and both are owner-blocked BY DESIGN rather than by any missing code.
  - 6.2 polarity A/B (light vs dark) for 'find the abandoned path' and 'find the missing-reporting node'.
  - 6.3 comparison-mode A/B (difference-map vs two-pane vs scrubber) on ERROR RATE AND TIME, not FPS.
  Both need human operators in front of the actual target display. The report (section 6) names them as the
  thing that SETTLES two open questions -- the best contrast polarity, and the max useful graph density
  before aggregation -- and it is explicit that both are empirical and hardware-dependent. Nothing in this
  repo can answer them, and a synthetic substitute would be exactly the kind of unearned green this artifact
  refuses. 6.3 additionally cannot be run as specified here: two of its three arms (difference map, scrubber)
  are NOT OFFERED, for reasons recorded in DECISIONS.md 5.2 and 5.3.

ACCEPTANCE — evidence per hard constraint (273 automated checks, 0 failures; self-test 29 detections)

  single file, no external refs   check_dist finds no sibling assets in dist/; src=http, href=http,
                                  @import and url(http are banned tokens, each self-tested against the
                                  REAL token rather than a paraphrase.
  no network                      fetch(, XMLHttpRequest, WebSocket, sendBeacon banned + self-tested.
  no forms, no storage            <form, localStorage, sessionStorage, indexedDB banned + self-tested.
  deterministic / read-only       Math.random banned; layout seeded by blake2b over stable IDs, never
                                  hash(); two opens of the file render with 0 differing canvas pixels.
  no runtime layout               forceSimulation, forceLink, forceManyBody, velocityDecay and
                                  simulation.tick banned + self-tested.
  no motion                       transition:, animation:, @keyframes, requestAnimationFrame, setInterval
                                  banned + self-tested. Verified by RENDERING: a control page built to
                                  differ under --force-prefers-reduced-motion moved 160000 px, proving the
                                  instrument bites; the artifact then differed by 0 px.
  never labelled LIVE             banned token; all ages derive from embedded timestamps.
  data in application/json        payload parses from the <script type="application/json"> block and
                                  carries generated_at and data_through.
  null never coerced to 0         renderer asserts core_luminance !== null and rail_width === null
                                  strictly; never-fired and fired-long-ago are different marks.
  no glow                         the Stage-0 contract gate REJECTS node.glow as a channel the spec never
                                  asked for -- proved by planting it and watching the gate raise.
  ages                            exactly one live clock read, inside age(), for the age of the PICTURE;
                                  every age of a thing IN the picture is baked at build time. Both halves
                                  asserted.
  both themes, same meaning       recency->salience monotone in both polarities; state hue drift <= 6.2deg;
                                  contrast floor 5.03 dark / 3.32 light; the page proven to respond to the
                                  preference by rendering, against a control proving the browser can switch.

  WHAT THIS ARTIFACT DOES NOT CLAIM, and where each absence is argued:
    no control charts (bands instead)        no series is recorded          DECISIONS 4.4
    no per-repo state timeline (rails)       no transitions are recorded    DECISIONS 4.5
    no loop-vs-human comparison (one side)   counterfactual not stored      DECISIONS 4.6
    no difference map                        previous == current            DECISIONS 5.2
    no timeline scrubber                     no wiring-version sequence,
                                             and staged transitions are
                                             motion, which is banned        DECISIONS 5.3
  Each of these is stated ON THE PAGE, not only here. That is the point of the whole exercise: the half
  the data supports is built, and the half it does not is NAMED rather than drawn convincingly.

MANUAL_CHECKS:
- (CLOSED 2026-08-05) headless browser load — Google Chrome was found at /Applications/Google Chrome.app. The verifier now opens dist/index.html from file:// headless with NetworkService disabled, twice, and compares canvas pixels. This is no longer a manual check.
- 6.2 and 6.3 are operator task-tests on target hardware and cannot be automated
LAST_RUN: 2026-08-06 -- POST-DONE owner request: a dark/light toggle button, Tailwind, and sans throughout with no monospace. All three done and verified; 287 checks pass, self-test 29 detections. Tailwind conflicted with the no-external-refs constraint, so it is COMPILED locally (styles/input.css -> tools/build-css -> styles/tailwind.css, committed) and inlined; pipeline/build.py stays pure Python and offline, with npm deliberately off its critical path. The palette stays CSS custom properties rather than Tailwind dark: variants, because the canvas resolves colours at draw time and because 6.1 verified that exact layering. The toggle's real risk was the canvas: it bakes colours into pixels, so setting data-theme alone gives a light page around a dark graph -- proved by deleting the redraw, after which 'clicking changes what is drawn' still PASSED while the canvas sat 27612 pixels stale. Four planted faults fired. Two pre-existing check defects surfaced and were fixed: a staleness test that asserted a literal string and started failing at midnight on an untouched artifact, and the fact that nothing asserted the page had a width -- the port dropped main's max-width and content ran off the viewport with everything green.
5.1 said that because every node carries previous_x/previous_y, 'where a node MOVED' was answerable. Checked it: WRONG. When the topology is unchanged the build writes Placed(n, prev, prev, prev, prev, 'carried') — previous is a COPY OF CURRENT from the same build. All 7 nodes had displacement 0.0. A diff drawn from that would show 'nothing moved' and the reader would conclude the layout is stable across versions, when no second version was ever compared. Carrying a previous field is not the same as having a prior version.
The test is now displacement, not presence — proved with two REAL builds: unchanged rebuild gives 0 moved and the mode says nothing was compared; a topology change gives 7 of 8 moved and the mode reports displacement as answerable. So the detector is correct in both directions and the mode will offer itself the moment the data supports it.
No empty diff panel is rendered. An empty diff is exactly the failure this project keeps naming: absence rendered as a measurement.
5.1'S OWN CHECK then caught a second defect: with NO nodes the new message claimed previous coordinates were self-copies, but there are no nodes to have any. Two different absences conflated; now distinguished.
Verified: self-test PASS (29 detections); verify 249/249 PASS. Published.
