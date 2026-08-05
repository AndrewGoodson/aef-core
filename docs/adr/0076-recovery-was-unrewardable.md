# ADR 0076: Recovery was unrewardable

## Status
Accepted. Phase 3 of the overnight run, closing ADR 0068 A3.

## Context

A run that hit a transient error and then completed the task was
**indistinguishable from one that gave up**:

```
RECOVERED         passed=False  error_count=1  plan_status=done
FAILED OUTRIGHT   passed=False  error_count=1  plan_status=failed
```

`Outcome.passed` required `error_count == 0`, so any error at all
disqualified the run. Three consequences, all reproduced:

- **G2** sees no difference, so a candidate that taught the agent to recover
  scores exactly like one that changed nothing.
- **G3** therefore cannot reward it, and G3 is the gate that decides whether
  a change is an improvement. Graceful recovery — one of the more valuable
  things an agent can learn — was **unrewardable by the objective the loop
  optimises**.
- **Harvest** promoted every recovered run into the corpus as a failure, so
  the corpus recorded successful recovery as the thing to stop doing.

## Decision

Fixed the way `policy_denied` was (ADR 0064): an explicit `recovered: True`
marker on the error entry, set by the node, **never inferred from error
text**. `Outcome` gains `recovered_errors`; `passed` tests
`unrecovered_errors == 0`.

Three properties this shape buys:

- **Absent means not recovered.** An agent that marks nothing is scored
  exactly as before. This is a strictly additive change.
- **The error is still reported.** `error_count` is unchanged and
  `recovered_errors` is counted alongside it rather than subtracted at
  classification time — "recovered from 2" and "had 0 errors" are different
  facts about an agent, and an owner reading a gate report needs both.
- **Recovery does not rescue an abandoned task.** `plan_status == "done"` is
  still required, so marking every error recovered cannot turn a failure
  into a pass.

Text inference was rejected without re-litigating it: ADR 0064 measured that
approach for policy denials and found it roughly *anti*-correlated with the
truth. A test pins that `"recovered from the timeout"` in the error string
does not count.

## What was deliberately not touched

`RuleBasedEvaluator.task_completion` — ADR 0038 and every existing user.
Verified as zero lines changed, and a test asserts `RECOVERED_KEY` does not
appear in that class. If the honest fix ever requires changing it, that is a
separate owner decision, not a side effect of this one.

## Also in this change

Two findings ADR 0074 recorded and deferred, both cheap and clearly right:

- **The archive's append-only property was never verified.** The ledger's
  hash chain is checked on every command; `archive.check_never_shrinks` had
  tests and **no production caller**. A deleted version left `status`
  reporting healthy while the rollback target the ledger names no longer
  existed. Now checked in `_preflight` alongside the ledger — and the
  detector was verified against a planted fault before being trusted.
- **`BLESSED` was invisible in the digest.** Every drift number is measured
  against the baseline, and the owner's weekly report never mentioned one
  had been set.

## Confidence
High on the mechanism; each case was reproduced and the default path is
provably unchanged. **Not claimed:** that anything currently *sets* the
marker. Nothing in this repo does, exactly as `policy_denied` is set only by
`PolicyEngine` — the key is the contract an agent's retry logic writes
against. Until an agent sets it, behaviour is identical to before, which is
the intended migration.
