STATUS: IN_PROGRESS
STAGE: 5 — Temporal modes (Stages 0-4 complete) (Stages 0 and 1 complete; dist/index.html now exists)
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
- [ ] 5.2 — temporal mode 2: two-date difference-map, two synced panes (primary "what changed")
- [ ] 5.3 — temporal mode 3: opt-in scrubber, staged transitions, explicit user action only; respect prefers-reduced-motion; all static end-states fully interpretable
- [ ] 6.1 — dual themes via prefers-color-scheme with identical semantic ordering (§3f verdict B)
- [ ] 6.2 — MANUAL: on-hardware polarity A/B (light vs dark) for "find the abandoned path" and "find the missing-reporting node"
- [ ] 6.3 — MANUAL: comparison-mode A/B (difference-map vs two-pane vs scrubber) measured on error rate and time, not FPS
NEXT: 5.2 — difference map. 5.1 established that a prior TOPOLOGY does not exist (one layout-state file, overwritten each build) but that every node carries previous_x/previous_y, so 'where a node MOVED' IS derivable while 'what was added or removed' is not. Build the derivable half — a displacement view — and state the rest, or conclude the mode cannot be offered at all. Do NOT fabricate a prior version.
BLOCKERS: none
MANUAL_CHECKS:
- (CLOSED 2026-08-05) headless browser load — Google Chrome was found at /Applications/Google Chrome.app. The verifier now opens dist/index.html from file:// headless with NetworkService disabled, twice, and compares canvas pixels. This is no longer a manual check.
- 6.2 and 6.3 are operator task-tests on target hardware and cannot be automated
LAST_RUN: 2026-08-05 — increment 5.1. The temporal frame is now NAMED on the page: ACCUMULATED PRESENT, everything observed up to data_through, explicitly not a snapshot of an instant. That matters because the two read identically at a glance and answer opposite questions — 'this path is thick' means it has carried a lot EVER, not that it is busy now. A reader who does not know which frame they are looking at assumes the flattering one.
Availability is DERIVED, not asserted. Checked the data: one layout-state file, overwritten each build, so no prior topology exists — but 7 of 7 nodes carry previous_x/previous_y. So 'where a node MOVED' is answerable and 'what was added or removed' is not, and the difference map says exactly that rather than claiming either.
MOTION BANNED OUTRIGHT rather than conditionally disabled. §5 requires respecting prefers-reduced-motion; having NOTHING TO REDUCE satisfies it unconditionally. Confirmed the page has zero transitions, keyframes, requestAnimationFrame or timers, then added all five as forbidden tokens with planted faults — unlike a media query, an absolute ban cannot be forgotten by the next element that wants a fade.
Verified: self-test PASS (24 planted tokens + 5 gate checks = 29 detections); verify 243/243 PASS. Published.
