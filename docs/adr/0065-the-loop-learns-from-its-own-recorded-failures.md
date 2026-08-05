# ADR 0065: The loop learns from its own recorded failures

## Status
Accepted. Implements Phase 2a — the wire between reflection and proposal.

## Context
`make_reflect_node` has written `MemoryRecord(kind="failure"|"success")`
since M0 (ADR 0046). `RuleBasedProposer` has grounded proposals in corpus
scenario ids since M8 (ADR 0054).

**Nothing connected them.** The system recorded a lesson from every run and
never read one back. That is self-*modifying* — it can change its own code —
but it is not self-*learning*, because the changes were never informed by
what the agent actually experienced. The gap was invisible because both
components were correct and both were tested; only the seam was missing,
which is the same shape as the defect ADR 0063 recorded.

## Decision

**1. A citation has a kind.** `SCENARIO` citations must name the train
split, as before. `MEMORY` citations name a `MemoryRecord` written by a
reflect node.

**2. Memory records carry no split, so the leak they enable is indirect —
and exact.** A reflect node running over a holdout scenario writes a record
whose `run_id` **is that scenario's id**. Citing that record leaks the
holdout by proxy, and the existing split check would never see it: it
inspects citations, and the citation names a memory id, not a scenario.

`MemoryEvidence.from_store(store, corpus)` excludes any record whose
`run_id` matches a validation or holdout scenario, and **reports what it
excluded** rather than silently dropping it.

**3. The rule is deny-what-is-known, not allow-what-is-proven.** A production
run has an arbitrary `run_id` appearing in no split, and production
experience is exactly what the loop exists to learn from — an allowlist would
exclude it and leave the proposer able to learn only from the corpus, which
is where it started. This is a deliberate departure from deny-by-default, and
it is safe *only because the leak has an exact signature*: the run id equals
the scenario id. If that ever stops being true, this rule stops being sound.

**4. A memory citation carrying a split is refused.** It would look like a
check while checking nothing — admissibility depends on the run that produced
the record, which `MemoryEvidence` decides, not on a field the caller sets.

**5. Empty evidence produces no proposal.** The proposer does not fall back
to speculating when it has learned nothing, and `propose_from_memory` returns
`()` rather than reaching for the corpus.

**6. The rationale is built from the recorded feedback**, not invented, so a
reader can trace a proposal back to the run that motivated it.

## Consequences
- 13 tests, each running the **real** reflect node through a **real**
  `GraphExecutor` into a **real** memory store, then proposing from what it
  recorded. The acceptance property — a recorded failure produces a grounded
  proposal citing it — is end-to-end, not stubbed.
- The proxy leak is tested for both validation and holdout, and the
  production-run case is tested to confirm it is *not* excluded.
- An ungrounded proposal is still impossible to construct (ADR 0054 holds).
- **What this does not do:** the proposer still only tunes module-level
  numeric constants. It now chooses *when* to propose based on real failures,
  but not *what* to propose — the mutation is still blind to the content of
  the feedback it cites. That is the next real limitation, and it is larger
  than this milestone.

## Alternatives Considered
- **Tag memory records with their split at write time.** Cleaner in
  principle, and rejected because it puts the security property in the hands
  of whoever calls `make_reflect_node`. Filtering at read time means the
  proposer cannot be handed inadmissible evidence even by a caller who
  forgets.
- **Allowlist admissible run ids.** Rejected: it excludes production runs,
  which is most of what there is to learn from.
- **Let the proposer query `MemoryStore` directly.** Rejected for the same
  reason `TrainOnlyEvidence` exists — a view the proposer cannot widen is
  stronger than a rule it is expected to follow.

## Confidence
High on the mechanism and the exclusion, both tested against real objects.
Medium on the *value*: the loop can now cite what it learned, but nothing
yet demonstrates that failure-grounded proposals are better than
corpus-grounded ones. That comparison needs the autonomous cycle running over
real traffic, and it has not run.
