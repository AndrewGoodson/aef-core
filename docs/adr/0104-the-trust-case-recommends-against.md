# ADR 0104: The trust case recommends against

## Status
Accepted. Milestone 6, and the end of the program's build phase.
**`docs/trust/promotion-trust-case.md` recommends NOT enabling Tier-1
auto-merge.** The switch remains the owner's and has not been touched.

## Why this is an ADR and not only a document

A recommendation in a markdown file goes stale silently: nothing fails when
the thing it describes changes. `tests/harness/test_trust_case.py` pins the
claims that would most mislead an owner if they drifted — that a fully passing
candidate still escalates, that no production call site passes
`tier1_enabled=True`, that the residual risk is still a number with a basis,
that the adversarial section still reports failures, and that the two
demonstrated weaknesses are still real. The last two fail **loudly if the
harness improves**, telling whoever fixed them to update the document rather
than letting it understate the system.

## The three findings that carry the recommendation

**Criteria 1 and 6 have never run against what their own text names.** They
say "against live traffic" and "stratified by tenant tag". Shadow execution
was exercised with a synthetic incumbent and candidate; the canary against
sample arrays, not tenants. What exists is a mechanism that would do those
things correctly when connected to something real, and that gap is not one
more test away.

**Shadow containment has a demonstrated bypass.** Suppression is
`PolicyEngine` with an empty scope set, which denies **tool calls**. A shadow
node that imports `pathlib` and writes is not making a tool call, and it wrote
to disk during a shadow run. ADR 0103 states this boundary in prose; stating
and demonstrating are different weights of evidence. It is fixable by running
the shadow inside Milestone 4's container, which is not built.

**Six adversarial rounds, six confirmed defects, in freshly written code.** The
rate has not fallen across the program's ~18 rounds and ~75 defects. Three
defects were introduced by the same session's own fixes. One was a fix for a
defect found that same hour, which G4 then rejected for the same class of
reason as the defect it fixed.

## The residual risk number

**5–10 false accepts per 100 gated candidates**, 1–3 of them actively harmful.

Its floor is principled: G3 requires the candidate beat the control cohort's
**p95**, so a candidate no better than a random mutation clears it about 5
times in 100 *by construction*. That is what a p95 threshold means, not a flaw
in it. The rest is corpus blind spots, plus an unquantified component for
everything the adversarial section describes.

It is labelled **derived, not measured**, because no population of 100 gated
candidates exists. "None" was not available as an answer: an owner expecting
zero will read the first false accept as a harness bug rather than as the rate
working as designed, and lose the ability to tell those apart.

## What I did not do

Enable Tier-1, propose enabling it, or build evidence shaped to support
enabling it. The prompt's first HARD-STOP says an agent that grants itself
merge rights on its own evidence is precisely the failure this harness exists
to prevent, and the honest form of compliance is a recommendation that can
reach "no" — which this one did.

The narrower step the document does recommend is not Tier-1: keep every
candidate escalating, and use the signed manifest to make approval cheap and
auditable. That reduces review load without removing the human the criteria
were written to protect.

## Confidence
High that the document is honest about the system: three of seven attacks
landed and are reported as they came out, including the one that most damages
the criterion doing the most work.

Low on its sufficiency as an independent assessment, and this is stated in the
document itself as reason #4 for the recommendation. **It was written by the
agent that built what it assesses.** A list of attacks by the author of the
defences is a lower bar than an adversary, and the four attacks that held were
each pushed once. That is an argument for an independent review, not against
this one.
