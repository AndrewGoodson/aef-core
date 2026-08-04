# ADR 0057: The loop runs from main; triggers are a security decision

## Status
Accepted. Implements M11 — the loop driver and its CI wiring.

## Context
Every harness module was built and tested, and **nothing drove them**. There
was no entry point that called `run_pipeline`, appended to the ledger,
archived, or evaluated a monitoring window. Building that orchestration
forced three decisions and surfaced one defect that only running the thing
could have found.

## Decision

**1. The loop is triggered by `workflow_dispatch` and `schedule` only, from
`main`. Never by a pull-request event.**

- `on: pull_request` runs the workflow file **from the PR's merge commit**,
  so a candidate branch that edits `.github/workflows/` would supply the
  very workflow that judges it. That is the trust boundary of ADR 0047,
  defeated one layer up.
- `on: pull_request_target` runs the base branch's workflow — which fixes
  that — but carries **full repository secrets**, and any step checking out
  and executing candidate code hands those secrets over. This is the classic
  "pwn-request" shape.

So the job runs from `main` and reaches out to the candidate itself. The
candidate is fetched as **data** (`read_candidate` /
`build_candidate_workspace`) and is never the context the job runs in — the
same shape as the library-level boundary, which sidesteps the problem rather
than defending against it.

`tests/harness/test_workflows.py` **asserts the forbidden triggers are
absent**, with an allowlist rather than a denylist. "We remembered not to add
it" is not a control, and this trap will look like a convenience improvement
to someone in six months.

**2. Ordering inside the driver is load-bearing.** State-location check →
kill switch → ledger chain → any work. A halt evaluated *after* the work is a
report, not a stop; a ledger verified after an append buries damage. Nothing
is written when the kill switch is engaged, not even a `PROPOSED` entry.

**3. Exit codes distinguish three outcomes.** `0` escalated (Tier-1 off),
`1` rejected, `2` **halted**. A workflow that cannot tell "this candidate is
no good" from "stop, something is wrong with the system" will retry the
second. An escalation exits `0` deliberately: a question is a successful run,
and a non-zero exit would train whoever reads CI to treat "needs your
decision" as "broken".

**4. A Zone B/C violation halts the loop**, it is not merely rejected.
`05-approval-policy.md` §6 makes it a halt criterion: a proposal reaching for
the judge is a category signal about the proposer, not a fact about one
candidate.

**5. Network-isolation attestation is a CLI flag passed by the workflow**,
never read from the environment inside `sandbox.py`. The value must come from
Zone B configuration, and an env read would put a security-relevant input
closer to the candidate. `--network-isolated` is passed only by `loop-gate`,
which runs in a `--network none` container; `loop-monitor` runs no candidate
code and neither needs nor claims it.

**6. The job is `permissions: contents: read` and references no secrets.**
A judge that can also push is not a judge.

## Consequences
- `aef loop gate | monitor | digest | status`, 40 tests across the driver and
  the workflows.
- **All six gates are always registered.** A gate with no evidence configured
  *fails* rather than being omitted — omitting would make a candidate look
  gated when it was not. In practice a repo with no corpus fails at G2, which
  is correct: no evidence, no merge.
- `status` reports rather than raises on a broken ledger, because it is what
  you run when something is wrong. `digest` is readable while halted —
  reading why the loop stopped is exactly what you want to do then.

### The defect running it found
With `--state .loop` **inside** the repository, an ordinary `git add -A`
sweeps the ledger and archive into the candidate's own commit. The ledger
then appears as added lines in the diff being judged, every candidate looks
like it touches Zone C, and the audit trail becomes part of what it audits.
Observed in a real smoke run, not predicted. The driver now **refuses** a
state directory inside the working tree, and both workflows were corrected to
`~/.aef-loop-state`.

## Alternatives Considered
- **Gate on `pull_request`.** Rejected — the candidate supplies its own judge.
- **`pull_request_target` with careful checkout discipline.** Rejected: it
  works only while every future step keeps the discipline, and the failure is
  silent secret exfiltration. Not triggering on PRs at all removes the class.
- **Document that state must live outside the repo.** Rejected after seeing
  it happen: deny-by-default, consistent with the rest of the harness.
- **Exit non-zero on escalation** so CI "fails" until the owner looks.
  Rejected: it makes red the normal state, and a permanently-red pipeline is
  an ignored pipeline.

## Confidence
High on the trigger decision and the ordering, both asserted by tests, and
the whole path was exercised end-to-end against a real repository (reject →
1, Zone B → security event, halt, exit 2, subsequent runs refused).

**Q-A5 remains OPEN, and is only partly addressed.** A failed job notifies
whoever watches GitHub Actions email for the repo — better than nothing,
worse than a channel. It still depends on the owner noticing an email, which
`05-approval-policy.md` §7 explicitly says it must not. A pager, a Linear
ticket, or an SMS hook is the real answer and is **not configured**. Recorded
as open rather than papered over.

**Also not automated:** nothing writes `observations.jsonl`. A deployment
running agents in production emits it; the loop only reads it. With no input,
every window reports as unobserved — which, correctly, rolls everything back.
