# ADR 0045: Tiered auto-merge replaces per-change owner review

## Status
Accepted (planning decision; no implementation yet). Amends ADR 0042.

## Context
ADR 0042 made the owner's review-and-merge of every candidate the sole
promotion gate, and `02-risks.md` R3 named that review "load-bearing" —
the only control catching *intent* rather than regression.

The owner subsequently stated that the subject matter is outside their
expertise and that, in practice, they would approve anything passing the
gates.

That is decisive design input. A safety control requiring capability the
operator does not possess is not a control. Retaining it would mean the
system's stated primary assurance is a step that does not actually occur —
strictly worse than designing for its absence, because real assurance gets
deferred to a fiction.

Anthropic's published position points the same way: *"effective oversight
doesn't require approving every action but being in a position to intervene
when it matters"*; prescribed interaction patterns *"create friction
without necessarily producing safety benefits"*
([measuring agent autonomy, 2026-02-18](https://www.anthropic.com/research/measuring-agent-autonomy)).

## Decision
**Two tiers.**

**Tier 1 — auto-merge, no human.** All gates pass *and* the gates have
genuine evidence: diff confined to Zone A, within size budget, every
previously-passing scenario still passes, beats the null-hypothesis control
cohort on the held-out set, within rate/drift budget, corpus coverage
exists for the changed behaviour, no concurrent candidate. Expected to be
the majority.

**Tier 2 — escalate.** Triggered exactly where gates produce **no signal**:
novel change class without corpus coverage, drift budget exhausted,
rebaseline request, diff over budget, concurrent-candidate race, or
unresolved post-merge anomaly. Escalations are phrased as decisions a
non-expert can make, never as code diffs.

**Zone B (the harness) remains permanently outside auto-approval**, and a
diff reaching it is a security event, not a proposal.

Because pre-merge human review is gone, four mechanisms become
load-bearing: post-merge monitoring with **auto-rollback**,
rollback-by-default on ambiguity, a **kill switch**, and a **weekly
trend digest** as the owner's real oversight surface.

Full policy: `docs/design/self-rewiring/05-approval-policy.md`.

## Consequences
- Assurance now rests on mechanisms that actually execute rather than on a
  review that would have been a rubber stamp. This is the central gain.
- **No human catches intent pre-merge.** A subtly harmful change passing
  every gate now merges. This is a real and accepted increase in risk,
  recorded rather than minimised.
- Detection latency moves from pre-merge to post-merge; the monitoring
  window becomes the exposure window, which is why rollback-by-default on
  ambiguity is mandatory.
- The human gate that remains is one the owner can genuinely exercise:
  rare, and framed as a judgement rather than a code review.
- Halt criteria are explicit (`05-approval-policy.md` §6), including "no
  measurable benefit over the owner editing code directly" — the program
  should stop for cost-benefit reasons, not only safety ones.
- ADR 0042's core stands (evolution engine disabled; no unattended
  *runtime* self-modification). What changed is *who approves a merge*, not
  whether the agent may rewrite live systems unattended — it may not.

## Alternatives Considered
- **Keep per-change review (ADR 0042 as written).** Rejected: the operator
  has stated it would be a rubber stamp. Keeping it would leave the
  system's primary control nominal, and would suppress investment in the
  post-merge mechanisms that must now carry the load.
- **Auto-merge everything, including Zone B.** Rejected on logical, not
  cautionary, grounds: an agent able to modify its judge is not judged, and
  approving that once approves everything thereafter. DGM removed its own
  hallucination detectors under sandboxing and human supervision
  ([arXiv 2505.22954](https://arxiv.org/abs/2505.22954)).
- **Risk-scored auto-merge (auto-merge below a threshold).** Rejected for
  v1: it requires a trustworthy risk score for arbitrary code changes,
  which does not exist. Corpus coverage is a better-grounded proxy and is
  what Tier 1 condition 7 uses instead.
- **Require a second AI reviewer instead of the human.** Deferred, not
  rejected — plausible as a later addition, but it is not independent
  assurance if it shares the proposer's failure modes, and it must never
  be the thing that authorises Zone B.

## Confidence
High that this is better than the policy it replaces, *given the stated
operator constraint* — the comparison is against a rubber stamp, not
against expert review. Medium on the overall risk posture: the design now
depends on post-merge monitoring quality, which is unbuilt and unproven,
and on the diff-size and coverage heuristics in Tier 1, whose thresholds
are open questions (Q-A1, Q-A2). Explicitly **not** claimed: that this is
as safe as a competent human reviewing every change.
