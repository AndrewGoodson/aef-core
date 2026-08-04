# ADR 0042: The owner's merge to `main` is the promotion gate; the evolution engine stays disabled

## Status
Accepted, **with a correction** (2026-08-04): the claim that owner-merge is
"strictly stronger" than Phase-4 criterion 7 is **false**. It is *broader in
authority* (every change is reviewed, at any risk level) but **weaker in
evidence**: it drops signed release manifests, and has no shadow execution
against the real traffic distribution and no canary — post-merge a change is
100% live, and rollback requires a process reload, the cold start criterion 6
exists to prevent. Criteria 1 and 6 are therefore *unmet*, not *unnecessary*;
`04-review-and-self-coding-redesign.md` §2.6 adds post-merge monitoring and
auto-rollback as partial compensation. The core decision (owner merge is the
sole promotion gate; evolution stays disabled) stands.

## Context
aef-core already declares an evolution engine for *unsupervised runtime
auto-promotion* of graph mutations, disabled in code at two layers:
`EvolutionConfig.__post_init__` raises `NotImplementedError` when
`enabled=True` (`aef/evolution/engine.py:48-55`), and
`EvolutionSettings._must_stay_disabled` raises a pydantic `ValueError` at
config-load time (`aef/config/schema.py:79-88`). Enabling it requires all
seven Phase-4 gate criteria (`engine.py:11-30`), of which criterion 7 is
human approval above a risk threshold with signed release manifests.

The self-rewiring program needs a promotion mechanism: something that
decides when a proposed wiring becomes the live wiring. The owner's stated
requirement is that they approve every change before it reaches `main`, and
that this is the only human gate.

## Decision
**The owner's review-and-merge to `main` is the promotion mechanism.**
Agents propose on `self-rewiring/<topic>` branches; automated gates
(G0–G5) run there; surviving candidates are surfaced as a branch diff plus
a validation report; **only the owner merges.**

**The evolution engine is not enabled, now or as part of this program.**
Its disablement at both layers remains untouched. This program builds a
separate, non-evolution archive rather than implementing `ArchiveStore`
(`engine.py:77-83`).

## Consequences
- **This is strictly stronger than criterion 7,** not a workaround for it.
  Criterion 7 permits unattended promotion *below* a risk threshold; this
  design permits none — every change is reviewed regardless of risk score.
- Criteria 1 (shadow execution) and 6 (canary rollout) become unnecessary
  **because their purpose is unmet elsewhere**: they exist to protect live
  traffic during *unattended* promotion. No unattended promotion occurs, so
  there is no such window to protect.
- Criteria 3 (golden-trace regression), 4 (bounded mutation rate), and 5
  (cumulative-drift monitoring) remain fully load-bearing and are carried
  into the design as gates G2 and G5. They protect against regressions and
  drift that a human reviewer cannot reliably catch by eye.
- Criterion 2 (null-hypothesis baseline) is deferred with its exposure
  recorded (`02-risks.md` R1) — the largest known weakness of v1.
- The automated gates exist to make the owner's gate **meaningful rather
  than a rubber stamp**: a candidate failing any gate is auto-rejected and
  never surfaced, so the owner's attention is spent only on changes that
  already provably don't regress.
- **Honest limitation:** automated gates catch regressions, not intent. A
  subtly harmful change that passes every gate is indistinguishable from a
  good one to the pipeline. The owner's diff review is therefore
  load-bearing and cannot degrade into formality without losing the primary
  control (`02-risks.md` R3).
- If unattended auto-promotion is ever genuinely wanted, that is a separate
  decision requiring all seven criteria — this ADR does not open that door.

## Alternatives Considered
- **Implement the seven criteria and enable the evolution engine.**
  Rejected: it is far more work for a *weaker* safety posture in this
  setting. The owner is willing to review every change, which dominates any
  automated promotion policy.
- **Auto-merge changes that pass all gates, with the owner reviewing after
  the fact.** Rejected: it inverts the control the owner explicitly asked
  for, and post-hoc review of an already-live change is a fundamentally
  different (weaker) guarantee.
- **Use a risk threshold so low-risk changes auto-merge.** Rejected for v1:
  it reintroduces criterion 7's unattended window and requires a
  trustworthy risk score, which does not exist for wiring changes.

## Confidence
High. The mapping from each Phase-4 criterion to "still needed / made
unnecessary by the owner gate" was done criterion by criterion against the
verbatim text, and the decision strengthens rather than weakens the
existing safety posture. The one judgement call — that criteria 1 and 6 are
genuinely unnecessary rather than merely inconvenient — rests on the fact
that both exist solely to protect unattended live promotion, which this
design does not perform.
