STATUS: IN_PROGRESS
STAGE: 1 — Generation pipeline (Stage 0 complete)
CHECKLIST:
- [x] init.scaffold — pipeline/ dist/ fixtures/ tools/ created; RESEARCH_REPORT.md installed
- [x] init.fixtures — synthetic dataset covering every required edge case (fixtures/fleet.json)
- [x] init.verifier — tools/verify created, self-test passes on 14 planted faults
- [x] 0.1 — encoding contract as CODE: a validator that refuses to emit a visual property when its backing field is null, and forces the UNKNOWN construction (hatched interior, broken border, "?")
- [x] 0.2 — build fails unless 100% of node/edge visual properties have a named backing field (report §6 Stage 0 threshold)
- [ ] 1.1 — pipeline: derive traversal graph from the event log
- [ ] 1.2 — pipeline: offline layout, deterministic seeding only (weighted centroid of positioned neighbours; perimeter by hash of stable ID; never Math.random)
- [ ] 1.3 — pipeline: carry previous_x/previous_y forward; bounded relaxation within a hard displacement budget of ~1 node diameter per layout version; store layout_reason
- [ ] 1.4 — pipeline: embed graph + positions + history + generated_at + data_through + expected interval in a <script type="application/json"> block
- [ ] 2.1 — vendor d3-force (8.3 KB min, ISC) locally; never fetched at view time
- [ ] 2.2 — hand-written Canvas renderer: node channels per §4.1 (position/radius/fill/border/interior glyph/birth flag; ≤3 preattentive variables; no glow, ever)
- [ ] 2.3 — two-layer edge model per §4.2: history rail width = log1p(lifetime_traversal_count), activity core luminance = recency
- [ ] 2.4 — the five endpoint states, each visually distinct: never-observed / dormant / retired / unknown / stale
- [ ] 2.5 — mid-edge gate glyph as a RECTANGLE (§3c verdict B), states [H…] [H✓] [H✗] [H!] [H↶]
- [ ] 2.6 — legend with concrete worked examples, windows, numbers, and every log/sqrt transform and cap printed
- [ ] 3.1 — persistence: a file reopened later renders pixel-identical node positions (threshold: zero coordinate drift between two opens)
- [ ] 3.2 — birth-flag tab ("NEW"/"3h"/"2d") computed from now − first_seen_at against embedded generated_at; static, not a halo (§3d verdict B)
- [ ] 3.3 — staleness self-display: all visible ages computed from embedded timestamps; never labelled LIVE
- [ ] 4.1 — dashboard: registry LEFT-JOIN telemetry; coverage + freshness strip first
- [ ] 4.2 — dashboard: exception queue (rollbacks, gate-eval errors, stale reporting, long-pending decisions) — NOT ordinary rejections
- [ ] 4.3 — dashboard: CONSORT-style cohort flow, neutral colours for expected rejection branches, red only for operationally abnormal (§3b verdict B)
- [ ] 4.4 — dashboard: Shewhart process-stability bands beneath the flow
- [ ] 4.5 — dashboard: fleet table with state-timelines; stale repos float to TOP; never retain a last green fill as dominant after reporting stops
- [ ] 4.6 — loop-vs-human panel labelled OBSERVATIONAL; disclose that the direct-human-edit counterfactual is not stored
- [ ] 5.1 — temporal mode 1: default accumulated present
- [ ] 5.2 — temporal mode 2: two-date difference-map, two synced panes (primary "what changed")
- [ ] 5.3 — temporal mode 3: opt-in scrubber, staged transitions, explicit user action only; respect prefers-reduced-motion; all static end-states fully interpretable
- [ ] 6.1 — dual themes via prefers-color-scheme with identical semantic ordering (§3f verdict B)
- [ ] 6.2 — MANUAL: on-hardware polarity A/B (light vs dark) for "find the abandoned path" and "find the missing-reporting node"
- [ ] 6.3 — MANUAL: comparison-mode A/B (difference-map vs two-pane vs scrubber) measured on error rate and time, not FPS
NEXT: 1.1 — pipeline: derive the traversal graph from the event log. Consecutive execution records within one run are the edge traversals; no new collection.
BLOCKERS: none
MANUAL_CHECKS:
- headless browser load of dist/index.html from file:// with network blocked — no headless browser confirmed available in this environment yet; the forbidden-token scan and single-file check run, the actual offline load does not
- 6.2 and 6.3 are operator task-tests on target hardware and cannot be automated
LAST_RUN: 2026-08-05 — increment 0.2, Stage 0 COMPLETE. `assert_complete()` fails the build in four directions: a required property with no channel, a channel the spec never asked for, a renderer painting something unbacked, and a declared channel no painter uses (ADR 0092's dead-entry class). REQUIRED_VISUAL_PROPERTIES is transcribed from report §4.1/4.2, NOT derived from the catalogue — deriving it from what was implemented would make the check tautological. `node.shape` is declared a CONSTANT that encodes nothing, because an omission and a decision look identical in a missing entry. All four faults planted and caught, plus a control proving the gate does not fire on an honest renderer — a gate that always raised would catch all four and be useless. Also corrected the self-test's own summary, which reported 14 checks when 19 had run.
Verified: self-test PASS (14 planted tokens + 5 gate checks = 19 detections, no false positives); verify 27/28 PASS; dist/index.html FAIL — expected, nothing is built until Stage 2.
