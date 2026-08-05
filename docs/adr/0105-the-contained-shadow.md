# ADR 0105: The contained shadow

## Status
Accepted. Closes the bypass the trust case demonstrated (§2.1). **Does not
change the recommendation** — see "What this does not fix".

## The bypass

Shadow execution suppresses a candidate's effects with `PolicyEngine` and an
empty scope set. That denies **tool calls**. A node that imports `pathlib` and
writes to disk is not making a tool call, and it wrote:

```
BEFORE  — in-process shadow
  host marker written: True    <-- the bypass
```

ADR 0103 stated this boundary in prose. Stating and demonstrating are
different weights of evidence, and the trust case's adversarial section
produced the demonstration.

## The fix, and why it uses the inverted-control worker

`contained_candidate_graph` builds the candidate's graph from a
`NodeWorkerSession` whose worker runs **inside** the Milestone 4 container —
no network, read-only root, `--cap-drop ALL`, one writable mount.

The obvious cheaper fix is to sandbox the whole shadow run. That would be
wrong here for a reason specific to shadowing: **a candidate that reports its
own final state can report the incumbent's and hide a divergence, making
itself look SAFER than it is.** That is the candidate-authored-evidence
problem ADR 0094 solved for the gate, and it bites harder here — in the gate a
forged result inflates a score; in a shadow it erases the signal promotion
eligibility is read from.

So the parent keeps state, routing and the step count, and the worker
evaluates one node and returns `(delta, route)`. The only thing a contained
candidate can lie about is one node's output, which *is* its behaviour — the
thing being measured.

## Verified, in both directions

```
AFTER   — same candidate, executed inside the container
  host marker written: False
  divergence recorded: candidate_failed='NodeEvaluationError: FileNotFoundError…'
  served to user     : incumbent state, working_memory={}
```

The in-process bypass is pinned by a test asserting it is **still real**,
because "the marker was not written" is also what a candidate that never ran
looks like.

That first containment is partly accidental — the host path does not exist
inside the container — so the read-only root is verified separately on paths
the image really has:

```
  /etc/hosts                       OSError
  /opt/aef/aef/__init__.py         OSError
  /tmp/x                           OSError
  /aef-workspace/ok.txt            WROTE   <-- the workspace, deliberately
```

## Two defects avoided by having found them before

**`close()` would have leaked a container.** It killed the process group, and
for a containerised worker the process group is the `docker run` **client**;
the daemon owns the container. That is ADR 0093's defect and Milestone 4's,
and this would have been its third location. Fixed before the first run, and
pinned by a test that checks `docker ps`.

**`sys.executable` is meaningless inside an image.** The parent's venv path
resolves to nothing there, and the failure reads as a broken entrypoint rather
than a wrong interpreter. `PYTHON_IN_CONTAINER = "python"` is named for that
reason.

## The adversarial round

Four attacks against the fix, all run:

```
  F1 network egress from the contained shadow    blocked (OSError)
  F2 write to the workspace mount's parent       Read-only file system
  F3 spawn a subprocess that outlives the node   contained; dies with the container
  F4 read the host filesystem                    /Users/... not visible
  F5 containers leaked after close()             0
```

**No confirmed defect. This is the first dry adversarial round in the
program**, and the honest qualification is that the surface was narrow — one
new function, one flag on an existing one, and two known defect shapes I was
specifically watching for. One dry round on a small surface is not evidence
that the rate has fallen; the program's own stopping rule wants two
consecutive, on the whole system.

## Containment is now the DEFAULT (revision)

The owner made the call the section below deferred. `ShadowRunner` **refuses
to construct** without a container session unless `uncontained=True` is passed
explicitly — the same shape `SandboxPolicy` already uses for network
isolation: refuse unless the containment is really there, and make running
without it something a caller states rather than inherits.

Every observation records `contained`, and a report is downgraded by **one**
uncontained observation, because a report is only as strong as its weakest
observation and averaging that away is how a mixed run reads as a clean one.
`SandboxCapabilities` exists for the same reason (ADR 0102): a result cannot
be read without knowing the conditions it ran under.

An AST test asserts nothing in `aef/` passes `uncontained=True` — a production
caller opting out would restore the bypass while every other test still
passed. The first version of that test grepped for the string and matched the
error message that *tells* a caller how to opt out, plus a `.pyc`; inferring a
call from text rather than reading the call is what ADR 0064 measured.

### The adversarial round on the default

Four attacks, three landed:

- **Any truthy object made the runner claim containment.** `session is not
  None` was the check, so a bare object produced `contained=True` while the
  candidate ran in-process — a false capability report, the class ADR 0102
  exists to prevent. Containment is now read from the session's own container,
  and a `NodeWorkerSession` built without one is refused for the same reason:
  a plain subprocess has real rlimits and no filesystem boundary.
- **A closed session was blamed on the candidate.** Reusing one recorded
  `contained=True` and a divergence reading `IsolationError: worker died
  before node` — a harness fault reported as candidate behaviour (ADR 0074),
  which makes a working candidate look broken. Now refused. `closed` is an
  explicit flag set by `close()`, because `poll()` returns None until the
  killed process is reaped and a session closed microseconds ago still read as
  open.
- **An empty report claimed `contained=True` over zero observations**, making
  "never ran" indistinguishable from the good case — the same reasoning that
  already made `divergence_rate` raise.
- **Dismissed:** `object.__setattr__` bypasses the frozen dataclass. It
  bypasses any frozen dataclass in Python, and anyone who can call it can call
  the underlying function directly, so it is not a boundary. Recorded so the
  dismissal is legible rather than an omission. `contained` is derived from
  the session rather than stored, so tampering with the field changes nothing.

## What this does not fix

**It needs an operator-supplied image** with `aef` importable — and now that
containment is the default, an adopter without one must pass `uncontained=True`
and will see `contained=False` on every observation. That is the intended
trade: the weaker mode stays available and stops being invisible. The tests
build an image and **skip** without it rather than passing.

**The workspace is still a host directory the candidate can write to.** That
is what a workspace is; containment means it cannot reach anywhere else.

**It does nothing for the criterion's central gap.** Criteria 1 and 6 still
have not run against the live traffic and real tenants their own text names.
That was the trust case's reason #1 and it is untouched by this.

## Consequences for the recommendation

Reason #2 of the trust case's recommendation is now **spent**: shadow
containment is the default, opting out is explicit, and the opt-out is
recorded on the evidence. Reasons #1, #3 and #4 are unchanged, and #1 was
always the strongest — criteria 1 and 6 still have not run against the live
traffic and real tenants their own text names. **The recommendation remains:
do not enable Tier-1 auto-merge.**

## Confidence
High on the fix, which is verified in both directions against a real container
and attacked four ways.

Moderate on its reach. It is one opt-in path; the default is unchanged, the
image is the operator's, and I have tested it against one image on one host.
