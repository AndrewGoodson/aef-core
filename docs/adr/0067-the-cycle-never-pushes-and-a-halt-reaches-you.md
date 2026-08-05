# ADR 0067: The cycle creates local branches only; a halt reaches the owner

## Status
Accepted. Implements Phase 2d and 2e. Resolves Q-A5.

## Context
Every piece of the loop existed and nothing invoked the proposer on a
schedule. And a halt still only failed a CI job, which depends on someone
reading GitHub email — exactly what `05-approval-policy.md` §7 says it must
not.

## Decision

**1. The cycle creates the candidate as a LOCAL branch and never pushes.**

This is what lets the whole loop run under `permissions: contents: read`.
Creating a branch in the runner's own checkout needs no repository permission
at all; **pushing** is what needs write access, and the gate job must never
have it (ADR 0057). So `aef loop cycle` writes the proposal, commits it
locally, gates it, records the decision, and stops. A test asserts the
branch-materialising function contains no `push`.

**2. At most one candidate per turn.** A loop that can emit many per cycle
exhausts the rate budget in a single run, and every candidate costs N+2
corpus passes to gate. Asserted by a test on the source, because the failure
mode is a `for` loop someone adds later that looks like an obvious
improvement.

**3. Order inside the cycle is the same as everywhere else**: kill switch,
then ledger chain, then any work. A halted loop writes nothing — not even a
`PROPOSED` entry — and a tampered chain stops it rather than being appended
to.

**4. Producing no candidate is a success, not an error.** No admissible
failure memory means no hypothesis. The cycle says so and exits 0; a proposer
that fell back to speculating when it had learned nothing would fill the
queue with exactly the ungrounded proposals ADR 0054 made unconstructible.

**5. Q-A5: three channels, none of them a secret in this repo.** On halt:
`HALT.md` at the repo root, a ledger entry, a non-zero exit, **and** a POST
to a webhook URL the owner sets outside the repository. The URL is read at
the **CLI boundary**, never inside the harness — same rule as the sandbox's
isolation attestation, for the same reason.

**A failed notification never hides the halt.** The kill switch is engaged
*before* the notifier runs, and a webhook exception is reported as
"POST FAILED; the halt still stands" rather than propagating.

**6. If no channel is configured the digest says so on every run**, in those
words. An unconfigured alarm that stays quiet is worse than none, because it
looks like a working one. The digest also reports when **no production runs
were recorded** — a repo that never passes `--record-runs` gets a corpus that
never grows, silently, which discharges the gap ADR 0066 left open.

## Consequences
- 16 tests. Every cycle test is a **refusal**: what it declines to do matters
  more than what it does, because what it does is change code.
- The daily cycle runs at 03:00 UTC in `loop-monitor.yml`, alongside the
  hourly monitor and the weekly digest. Triggers and `contents: read` are
  unchanged and still asserted.
- **The loop is now autonomous end to end except for merging.** It harvests,
  learns, proposes, gates, escalates, monitors, rolls back, halts, and tells
  you it halted. It does not merge, and it cannot enable its own merging.

## Alternatives Considered
- **Have the cycle open a PR.** Rejected: it needs write permission on the
  job that judges candidates, which is the concentration of authority ADR
  0057 exists to prevent.
- **Emit a patch artifact for a separate privileged job to apply.** Deferred
  — a reasonable shape, and it moves the trust boundary to whatever applies
  the patch, which then needs its own design.
- **Read the webhook URL from a config file in the repo.** Rejected: that is
  a secret in the repository wearing a different hat.
- **Retry a failed webhook.** Rejected for v1: a retry loop inside a halt
  path is a way to turn a halt into a hang.

## Confidence
High on the mechanism; every path is tested, including the failing-webhook
case. Medium on Q-A5 being genuinely *resolved*: three channels exist and one
of them reaches a phone, but **the owner still has to configure it**, and if
they do not, the digest's warning is itself something they have to read. That
is better than depending on a CI email and it is not the same as solved.
**Not claimed:** that the cycle produces useful proposals. It produces
grounded ones, from real recorded failures, and nothing yet shows they are
better than doing nothing — that needs the loop running against real traffic,
which has not happened.
