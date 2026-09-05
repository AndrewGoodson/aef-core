# ADR 0188: The second independent score

## Status
Accepted. BEYOND_90's J0, run a second time at the end of the night (UPGRADE_LOOP's S0b), on `main` at 6affc65.

## Context

ADR 0151 applied the control once: a blind reviewer scored 68.5 against our 86 and the lower score stood. Since then eleven self-graded rows were added, each on an artifact. The rubric's own preamble says a self-graded number is the failure the trust case warns about — so the control was applied again, blind to every ADR, the log, the loops, and the first review. Report committed verbatim: `docs/research/j0b-independent-score-2026-09-05.md`.

## The two score sets

| dim | weight | ours | J0b | resolution |
|---|---|---|---|---|
| 1 closed loop | 20 | 15 | 13 | **13** — verified, a live defect (below) |
| 2 what is learned | 20 | 12 | 12 | 12 |
| 3 reflection | 10 | 8 | 8 | 8 |
| 4 safety | 15 | 15 | 13 | **13** — verified |
| 5 evidence | 10 | 8 | 9 | **9** — see below |
| 6 archive | 10 | 6 | 7 | **7** — see below |
| 7 real signal | 10 | 4 | 3 | **3** — verified |
| 8 adoptability | 5 | 4 | 4 | 4 |
| | | **72** | **69** | **69** |

## Every disagreement, resolved

**Dim 1 (15 → 13).** J0b RAN this repo's own nightly command from `.github/workflows/loop-monitor.yml` against this repo's own corpus, which holds two graphs. It omits `--graph-id`; the ambiguous-corpus refusal (ADR 0176/0182) returned **exit 1**, which the workflow's own case statement reads as "REJECTED by a gate — the system working, not a broken job". A misconfigured loop reported as a healthy one: ADR 0139's shape, found by the reviewer, in the workflow three fix waves had already touched. Reasoning right; 13 stands. **Fixed in this commit:** `GraphIdError` returns `EXIT_ERROR` (3), the test that pinned it as a rejection is updated with the reason, and this repo's nightly cycle passes `--graph-id demo_agent` (pinned). The row does not go back up on the fix — that is what the next blind review is for.

**Dim 4 (15 → 13).** "Adversarial rounds exist as a document I was not allowed to read, not as an executable red-team suite. And a shipped hole the system admits itself: `aef loop digest` printed `Halt channel configured: NO`." Both true. Every adversarial round tonight was a seam-hunter agent whose findings became tests — but the rounds themselves are not re-runnable from the repo. Reasoning right; 13 stands. S5's +1 (ADR 0161) was for containment being the default, which J0b confirmed by running 64 container tests against a real daemon; the two points it deducted are different gaps.

**Dim 7 (4 → 3).** "0 `harvest`; every summary scenario's note reads 'synthetic passage; recorded live via claude_code'. Live model calls on author-written inputs is not live traffic." Correct, and stricter than J0's 4 for the same fact. 3 stands. M6's pilot (running as this is written) harvests real runs from a real repo's own objectives; S7 may re-earn on that artifact.

**Dim 5 (8 → 9) and Dim 6 (6 → 7) — taken upward.** J0 lowered dim 5 for measurements that existed only as prose; since then every S-worker committed a runner and raw data, and J0b — who could not read the ADRs — found the artifacts one directory away and scored the honesty on them. J0 lowered dim 6 for an in-memory archive with no CLI; J0b ran `aef loop run`, watched a stepping stone archived into a persistent hash-chained lineage store, and scored that. The rubric's first rule is that a score moves only on an artifact a reader can find. The blind reviewer IS that reader; when it finds more than we claimed, the claim was under-stated, not over-. Taking both. (J0b's remaining deductions on 5 — no `make measure` regenerating the tables in CI — and on 6 — no measured run where a stepping stone produced a better descendant, no owner-facing lineage listing — are recorded as the next increments.)

## Decision

The rubric heading is **69 / 100**. Five rows prepended citing this ADR. The delta since J0 (68 → 69) is what eleven increments, four seam hunts and ~50 reproduced fixes bought on the scoreboard — and, in the reviewer's own words, the loop "genuinely works when driven by hand", the adopter path is "verified end to end", and "the learning payoff is measured and negative, and honestly so".

## Consequences

The number barely moved and the system did. That is the honest reading: most of tonight's work was making claims true rather than making new ones, and a blind reviewer scores what is true. Three of J0b's findings are already fixed (the exit code) or in flight (the pilot); the rest — an executable red-team suite, a halt channel, a CI re-runner for the measurements, a lineage listing — are the next loop's first increments.
