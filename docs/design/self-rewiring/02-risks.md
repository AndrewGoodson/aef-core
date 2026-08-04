> **⚠ REVISED — read `04-review-and-self-coding-redesign.md` first.** Three-reviewer
> audit disproved this document's premise (edges authorize routes; nodes choose them)
> and found the gate pipeline admitted only no-ops. Scope is now self-coding with a
> structurally isolated harness (ADR 0044). Retained for provenance.

# Self-rewiring agents — 02: risk analysis

**Status:** planning artifact. No code accompanies this document.

A plan for self-rewiring agents that does not name reward hacking and
drift is not a plan. This document states the failure modes plainly,
including the ones the design does **not** solve.

**Framing note.** Automated gates catch **regressions**. They do not catch
**intent**. A change that is subtly harmful but passes every gate is,
by construction, indistinguishable from a good change to the pipeline —
which is why the owner's diff review is load-bearing and cannot be reduced
to a formality. Every risk below is scored on that understanding.

---

## R1 — Reward hacking (overfitting to the eval suite)

**What it looks like.** The proposer discovers rewirings that raise suite
scores without improving real behaviour: exploiting a `domain_gate`'s
literal condition, tuning to the specific scenarios in the corpus, or
finding a path that games `task_completion`'s `plan.status == "done"`
heuristic (`rule_based.py:29-36`) without doing the work.

**Likelihood: High.** This is the default outcome of any optimisation
process pointed at a proxy metric. It is not a possibility to guard
against; it is the expected behaviour absent countermeasures.

**Blast radius: High.** Scores improve while capability degrades, and the
metrics say everything is fine — the failure is invisible in exactly the
instrument you'd use to detect it.

**Mitigations in the design.**
- G4 prevents the proposer from editing the standard (the most direct form).
- G2 independently requires *behavioural* equivalence, so a score-chasing
  rewiring that changes behaviour is caught by a different instrument.
- G3's zero-tolerance rule (no previously-passing scenario may fail).
- Corpus growth over time shrinks the exploitable gap.

**Residual exposure: substantial.** The corpus is a **sample**, not a
specification. The only strong control is a **null-hypothesis baseline**
(Phase-4 criterion 2, `engine.py:14-17`): require a candidate to beat a
*randomly mutated* control, not merely the incumbent, which distinguishes
real signal from noise-fitting. **It is deferred (Q2) and its absence is
the largest single weakness in v1.**

**Halt trigger.** Suite scores trending up while owner review increasingly
finds changes that look wrong — or any confirmed instance of a scored
improvement that a human judges a regression.

---

## R2 — Cumulative drift

**What it looks like.** Ten changes, each individually compliant and
individually sensible, land the graph somewhere no one would have chosen
in one step. This is a **documented** failure mode, not a hypothetical:
criterion 5 exists because "several compliant edits produced a later
regression" (`engine.py:23-25`).

**Likelihood: High** over any extended run. It requires no adversarial
behaviour — it is the emergent result of many locally-optimal steps.

**Blast radius: Medium-High.** Degradation is gradual, so it is typically
noticed late, and attributing it to any single change is impossible by
construction.

**Mitigations.** G5 is designed specifically for this: drift measured from
an **owner-blessed baseline** (not from the previous version, which would
reset to zero and measure nothing), plus a rate limit bounding frequency.
Rebaselining is owner-only and constitutes an explicit "I accept where we
are."

**Residual exposure: moderate.** The drift *metric* (Q-G5-2) is the weak
point — a poorly-weighted distance function will either fire constantly or
never. Expect to tune it against real proposal history.

**Halt trigger.** Drift budget exhausted twice in quick succession, or a
regression that bisects to no single change.

---

## R3 — A malicious-but-passing diff

**What it looks like.** A change that satisfies G0–G5 completely and is
still harmful: exfiltration via a rewired tool sequence, a prompt `param`
that changes what a tool is asked to do, or a routing change that skips a
validation node in a case the corpus doesn't cover.

**Likelihood: Low** in the intended setting (a first-party proposer over a
reviewed palette). **Not zero**, and rises sharply if the proposer becomes
LLM-backed and prompt-injectable through the content it reads.

**Blast radius: High** — by definition it is the case where every automated
control returned green.

**Mitigations.**
- G0's palette: the agent cannot introduce new code, only recombine
  reviewed refs — which bounds *what can happen* even in the worst case.
- `PolicyEngine` remains deny-by-default with HITL above the risk threshold
  (`security/tool.py`), untouched by this program, so tool calls are
  independently gated at execution time.
- G0 forbids removing an existing `requires_human_approval` flag.
- **The owner's diff review.** This is the actual control. A manifest diff
  is small and human-legible precisely so this review is tractable.

**Residual exposure: this risk is not eliminated, and must not be
represented as eliminated.** The design reduces it to "a human reads a
small, structured diff." That is a good position; it is not a guarantee.
If the owner stops genuinely reading diffs, this control is gone and
nothing replaces it.

**Halt trigger.** Any proposal that attempts a G4 violation (an attempt to
alter the judge is a category signal, not a normal failure), or any
approved change later found harmful.

---

## R4 — Corpus rot

**What it looks like.** The golden corpus ages: scenarios encode outdated
assumptions, stop reflecting real usage, or bake in bugs as "expected."
Gates keep passing while protecting the wrong thing. Alternatively the
corpus is never grown, so coverage falls behind capability.

**Likelihood: Medium-High** on any long horizon. Test corpora rot by
default; this one rots faster because the system it guards is changing
deliberately.

**Blast radius: Medium.** It degrades the *quality* of every gate decision
simultaneously — G2 and G3 both read from it.

**Mitigations.** Never-shrinks enforcement (git-visible removals + a CI
assertion) prevents silent erosion. Agents may **nominate** scenarios but
never modify the corpus (G4), so growth is owner-driven and deliberate.

**Residual exposure: moderate.** "Never shrinks" prevents deletion but does
not prevent **staleness** — an accumulating corpus of increasingly
irrelevant scenarios is a distinct failure the design does not currently
address. **Recommendation: a periodic owner review of corpus relevance,
scheduled rather than ad hoc.** Recorded as an open question.

**Halt trigger.** Corpus unchanged across a long stretch of accepted
changes (coverage is falling behind), or a production failure in a path the
corpus nominally covered.

---

## R5 — Proposer degeneracy

**What it looks like.** The proposer stops producing useful candidates:
churning A→B→A, proposing no-ops, repeatedly re-proposing rejected ideas,
or fixating on one region of the graph.

**Likelihood: Medium**, especially for a first rule-based proposer.

**Blast radius: Low.** Wasted compute and owner attention; no correctness
impact. Every candidate still passes the same gates.

**Mitigations.** `GraphDiff.is_empty`-style no-op rejection; G5's rate limit
bounds volume; rejection records let the proposer avoid re-proposing.

**Residual exposure: low.** Mostly an efficiency and attention-budget
concern. Worth explicit reporting so owner attention is spent well.

**Halt trigger.** Sustained high rejection rate, or repeated identical
proposals.

---

## R6 — Gate infrastructure bugs

**What it looks like.** The gates themselves are wrong — a comparison
policy too loose (passes real regressions), too tight (rejects everything),
a non-deterministic fixture making G2 flake, or the never-shrinks assertion
silently not running.

**Likelihood: Medium.** This is new, non-trivial code, and this session's
own audit history shows how easily a gate can be subtly wrong (e.g. a HITL
threshold that made a security gate unreachable — ADR 0035).

**Blast radius: High** if a gate silently under-enforces — the entire
safety argument rests on the gates doing what they claim.

**Mitigations.** Each gate spec includes an explicit **known-bad test**:
a case the gate *must* reject (see each gate's "how this gate is tested").
Gates are deterministic control-plane code held to the repo's existing
green bar (pytest / mypy --strict / ruff), the same standard that has
carried 40 ADRs.

**Residual exposure: moderate.** Mitigated by treating gate code as
safety-critical: reproduce-first tests, no gate ships without its
known-bad case passing.

**Halt trigger.** Any gate found to have been under-enforcing in
production — pause acceptances until audited.

---

## R7 — Scope creep from rewiring toward self-coding

**What it looks like.** Pressure to let the proposer add new node
functions, because palette-bounded rewiring feels limiting. Each individual
relaxation seems reasonable; the endpoint is an agent writing arbitrary
code.

**Likelihood: Medium** — this pressure is predictable and will feel
justified when it arrives.

**Blast radius: Very High.** It removes the containment boundary that makes
the entire design defensible (`01-architecture.md` §2.1).

**Mitigation.** Recorded explicitly as **Q1**, with a recommendation of
**no for v1**, and an ADR making the palette boundary a deliberate,
documented decision rather than an incidental limitation — so relaxing it
would require consciously overturning a written decision.

**Halt trigger.** Any proposal to let agents author `fn` code should stop
the program for a fresh safety design, not proceed as an increment.

---

## Summary

| # | Risk | Likelihood | Blast radius | Residual after mitigations |
|---|---|---|---|---|
| R1 | Reward hacking | High | High | **Substantial** (no null-hypothesis baseline in v1) |
| R2 | Cumulative drift | High | Med-High | Moderate (metric needs tuning) |
| R3 | Malicious-but-passing diff | Low | High | **Not eliminated** — rests on owner review |
| R4 | Corpus rot | Med-High | Medium | Moderate (staleness unaddressed) |
| R5 | Proposer degeneracy | Medium | Low | Low |
| R6 | Gate bugs | Medium | High | Moderate |
| R7 | Creep toward self-coding | Medium | Very High | Low if Q1 holds |

**The two honest headlines:**

1. **R1 is the weakest point of v1.** Without a null-hypothesis baseline,
   the system can optimise a proxy. Deferring it is a defensible cost
   decision, but it should be a *decision*, not an oversight.
2. **R3 cannot be automated away.** The design's job is to make the owner's
   review small, structured, and tractable — not to replace it. If diff
   review degrades into rubber-stamping, the primary control against
   harmful-but-passing changes is gone.

---

## Open questions raised here

- **Q-R1** — accept R1's residual for v1, or pull the null-hypothesis
  baseline forward into the initial milestones?
- **Q-R4** — cadence for owner review of corpus *relevance* (never-shrinks
  handles deletion, not staleness).
- **Q-R6** — should gate code carry a higher bar than the standard green
  bar (e.g. mandatory mutation testing)?
