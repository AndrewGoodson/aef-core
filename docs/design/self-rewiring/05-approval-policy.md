# 05 — Approval policy: tiered auto-merge

**Status:** planning artifact. Supersedes the "owner reviews every change"
model in `01-architecture.md` §4.6 and ADR 0042's promotion mechanism.
Recorded as ADR 0045.

---

## 1. Why this exists

The original design made the owner's review of every diff the primary
safety control. The owner then stated plainly that, in practice, they would
approve anything that passed the gates — the subject matter is outside
their expertise.

That statement is **design input, not a failure of diligence.** A control
that requires capability the operator does not have is not a control; it is
a fiction. Worse, depending on it makes the system *less* safe than
designing honestly for its absence, because real assurance gets deferred to
a step that does not actually happen.

It also aligns with Anthropic's published position on autonomy: *"effective
oversight doesn't require approving every action but being in a position to
intervene when it matters"*, and prescribed interaction patterns *"create
friction without necessarily producing safety benefits"*
([measuring agent autonomy, 2026-02-18](https://www.anthropic.com/research/measuring-agent-autonomy)).

**The resolution is not to remove the human gate. It is to move it from
every change to the decisions a non-expert can actually make.**

---

## 2. The two tiers

### Tier 1 — Auto-merge (no human)

A candidate merges automatically when **all** hold:

| # | Condition |
|---|---|
| 1 | Diff confined to **Zone A** (`agents/**`) — enforced by the CI path allowlist (ADR 0044) |
| 2 | Diff size within budget (a change too large to be meaningfully verified is not Tier 1) |
| 3 | G0–G1 pass: static safety, import allowlist, builds, `mypy --strict`, existing suite green |
| 4 | G2: **every previously-passing scenario still passes** (zero tolerance) |
| 5 | G3: beats the **null-hypothesis control cohort** at the 95th percentile on the **held-out** set |
| 6 | G5: within rate and drift budget |
| 7 | Corpus coverage exists for the changed behaviour — the change is in a class the gates have evidence about |
| 8 | No concurrent candidate against the same incumbent (no race) |

Expected to be the large majority of candidates.

### Tier 2 — Escalate to owner

Escalation is **not** ceremony. It is triggered precisely where the gates
produce **no signal**, so automation has nothing to say:

| Trigger | Why the gates can't decide |
|---|---|
| Diff touches Zone B or C | Structurally rejected first (ADR 0044); escalated as a **security event**, not a proposal |
| Novel change class with no corpus coverage | Gates have no evidence about this behaviour |
| Drift budget exhausted | The question is "do we accept where we've drifted to?" — a judgement, not a measurement |
| Rebaseline requested | Owner-only by definition (G5) |
| Diff exceeds size budget | Unverifiable at scale; needs a human decision to split or reject |
| Two candidates race the same incumbent | Neither was gated against the other |
| Post-merge monitoring flags an anomaly the auto-rollback couldn't resolve | Ambiguous signal |

**Escalations are phrased for a non-expert.** Not a code diff — a decision:
*"The system wants to change behaviour it has no test coverage for.
Approve, reject, or require a test first?"*

---

## 3. What stays permanently outside auto-approval

**Zone B — the harness: gate code, golden corpus, eval suite, CI workflow.**

Not a preference. Arithmetic: **if an agent can modify what judges it, the
judgment carries no information.** Auto-approving changes to the judge is
auto-approving everything thereafter, including the ability to stop
detecting problems.

The Darwin-Gödel Machine — self-modifying, sandboxed, and under human
supervision — removed the tool-use markers used to detect its own
hallucinations ([sakana.ai/dgm](https://sakana.ai/dgm/),
[arXiv 2505.22954](https://arxiv.org/abs/2505.22954)). No approval policy
prevents that. Only write-scope does.

Enforcement is the ADR 0044 trust boundary: gates execute from the base
ref, never the branch. A Zone-B diff is rejected before any gate runs, and
reported as a security event.

---

## 4. What replaces pre-merge review

Removing the human from the merge path means detection must move
**after** it. These are now load-bearing, not optional:

1. **Post-merge monitoring + auto-rollback.** The primary safety net.
   Tracks outcome metrics on live runs against the pre-merge baseline;
   reverts automatically on regression.
2. **Rollback-by-default on ambiguity.** When monitoring is unclear, revert
   rather than persist. Reverting a good change costs little; keeping a bad
   one compounds.
3. **Kill switch.** One command halts the loop and freezes the current
   wiring. Documented where the owner will find it under stress.
4. **Weekly digest — the owner's real oversight surface.** Not diffs.
   Trends a non-expert can judge: acceptance rate, drift consumed,
   rollbacks triggered, escalations raised, scenarios added, and whether
   agent-authored changes are measurably beating a human editing code.
5. **Immutable proposal ledger.** Every candidate, gate outcome, merge, and
   rollback — so any regression can be bisected to a change.

---

## 5. Honest accounting

**This is riskier than a genuinely-reviewing expert.** It trades a control
that does not work for controls that do. The net is probably better; it is
not equivalent, and this document does not claim otherwise.

Specifically weaker:
- No human catches *intent* pre-merge. Gates catch regressions, not
  motives. A subtly harmful change that passes every gate now merges.
- Detection latency moves from pre-merge (instant) to post-merge
  (monitoring window).

Specifically stronger than the fiction it replaces:
- Assurance now rests on mechanisms that actually execute, rather than on
  a review step that would have been a rubber stamp.
- Escalations are rare and answerable, so the human gate that remains is
  one the owner can genuinely exercise.

---

## 6. Halt criteria

Stop the loop — kill switch, wiring frozen, owner notified — on any of:

1. **A rollback triggered by something the gates passed.** The gates have a
   blind spot; do not keep merging through it.
2. **Any Zone-B or Zone-C violation attempt.** A proposal reaching for the
   judge is a category signal, not a normal rejection.
3. **Drift budget exhausted twice in quick succession.**
4. **Two consecutive escalations resolved by rejection** — the proposer is
   working outside its evidence base.
5. **No measurable benefit over the owner editing code directly**, after a
   defined trial. Then the program is cost without benefit and should stop
   regardless of safety.

---

## 7. Open questions

| # | Question | Recommendation |
|---|---|---|
| Q-A1 | Diff-size budget value (lines? files? cyclomatic delta?) | Start restrictive; loosen only with evidence |
| Q-A2 | Monitoring window before a change is considered "settled" | Long enough to see real traffic variety |
| Q-A3 | Does Tier 1 need a cooling-off delay before merge, to allow a manual veto? | Cheap insurance; recommend yes for the first N merges |
| Q-A4 | Digest cadence — weekly, or per-N-merges? | Whichever produces a digest the owner actually reads |
| Q-A5 | Who is notified on halt, and how? | Must not depend on the owner watching a terminal |
