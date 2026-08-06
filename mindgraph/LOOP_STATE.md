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
- [x] 5.2 — difference map NOT OFFERED: nothing has been compared. Detector in place so it becomes available the moment a build actually relaxes (see DECISIONS.md), two synced panes (primary "what changed")
- [ ] 5.3 — temporal mode 3: opt-in scrubber, staged transitions, explicit user action only; respect prefers-reduced-motion; all static end-states fully interpretable
- [ ] 6.1 — dual themes via prefers-color-scheme with identical semantic ordering (§3f verdict B)
- [ ] 6.2 — MANUAL: on-hardware polarity A/B (light vs dark) for "find the abandoned path" and "find the missing-reporting node"
- [ ] 6.3 — MANUAL: comparison-mode A/B (difference-map vs two-pane vs scrubber) measured on error rate and time, not FPS
NEXT: 5.3 — timeline scrubber. 5.1 established no SEQUENCE of versions is retained (one state file, overwritten each build), and motion is banned outright so §3g's staged transitions cannot be animation anyway. Expect this to be unavailable too; state it and move on rather than inventing a sequence.
BLOCKERS: none
MANUAL_CHECKS:
- (CLOSED 2026-08-05) headless browser load — Google Chrome was found at /Applications/Google Chrome.app. The verifier now opens dist/index.html from file:// headless with NetworkService disabled, twice, and compares canvas pixels. This is no longer a manual check.
- 6.2 and 6.3 are operator task-tests on target hardware and cannot be automated
LAST_RUN: 2026-08-05 — increment 5.2. The difference map is NOT OFFERED, and finding out why corrected an overclaim I made in 5.1.
5.1 said that because every node carries previous_x/previous_y, 'where a node MOVED' was answerable. Checked it: WRONG. When the topology is unchanged the build writes Placed(n, prev, prev, prev, prev, 'carried') — previous is a COPY OF CURRENT from the same build. All 7 nodes had displacement 0.0. A diff drawn from that would show 'nothing moved' and the reader would conclude the layout is stable across versions, when no second version was ever compared. Carrying a previous field is not the same as having a prior version.
The test is now displacement, not presence — proved with two REAL builds: unchanged rebuild gives 0 moved and the mode says nothing was compared; a topology change gives 7 of 8 moved and the mode reports displacement as answerable. So the detector is correct in both directions and the mode will offer itself the moment the data supports it.
No empty diff panel is rendered. An empty diff is exactly the failure this project keeps naming: absence rendered as a measurement.
5.1'S OWN CHECK then caught a second defect: with NO nodes the new message claimed previous coordinates were self-copies, but there are no nodes to have any. Two different absences conflated; now distinguished.
Verified: self-test PASS (29 detections); verify 249/249 PASS. Published.
