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

## What this does not fix

**It is opt-in.** `ShadowRunner` with an in-process graph behaves exactly as
before, and that is still the default. Making containment mandatory means
requiring every adopter to supply an image, which is a decision with a cost
and is the owner's.

**It needs an operator-supplied image** with `aef` importable. The tests build
one and **skip** without it rather than passing.

**The workspace is still a host directory the candidate can write to.** That
is what a workspace is; containment means it cannot reach anywhere else.

**It does nothing for the criterion's central gap.** Criteria 1 and 6 still
have not run against the live traffic and real tenants their own text names.
That was the trust case's reason #1 and it is untouched by this.

## Consequences for the recommendation

Reason #2 of the trust case's recommendation weakens and does not disappear:
the criterion doing the most work for promotion is contained only when someone
opts in. Reasons #1, #3 and #4 are unchanged. **The recommendation remains: do
not enable Tier-1 auto-merge.**

## Confidence
High on the fix, which is verified in both directions against a real container
and attacked four ways.

Moderate on its reach. It is one opt-in path; the default is unchanged, the
image is the operator's, and I have tested it against one image on one host.
