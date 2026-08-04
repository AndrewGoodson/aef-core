# ADR 0055: The proposal ledger is a hash chain, and the report leads with the
decision

## Status
Accepted. Implements M9.

## Context
Under tiered auto-merge (ADR 0045) there is no human in the merge path, so
the ledger *is* the audit trail rather than a convenience alongside one. And
`05-approval-policy.md` §2 requires escalations to be "phrased as decisions
a non-expert can make, never as code diffs" — a requirement that is honoured
or quietly broken by how the report is laid out.

## Decision

**1. The ledger is a hash chain, verified on read.** Each entry carries the
SHA-256 of the previous one. "Append-only by convention" is not a property,
it is a hope: a system that can merge its own changes could also, in
principle, edit the record of having done so. Altering, removing, or
reordering an entry breaks every link after it.

Verification happens **on read**, not through a separate `verify` command a
person has to remember to run. A ledger checked only when someone thinks to
check it is not evidence.

**Appending onto a broken chain is refused.** Extending damage would bury
the tampering further from where it happened.

**2. The report leads with the decision and puts the diff last.** A report
that opens with a diff invites exactly the rubber stamp the tiered policy
was created to eliminate — the owner scrolls, sees code they cannot
evaluate, and approves. Order is: what is being asked → why it was proposed
→ the evidence → what the checks found (with numbers) → the diff.

**3. `decide()` takes `tier1_enabled` explicitly and it is off everywhere.**
A fully passing pipeline **escalates**, and the escalation says why: with no
human in the merge path *and* nothing watching afterwards, an auto-merge
would be unobserved in both directions. The question posed is answerable
without reading code.

**4. A security event rejects rather than escalating.** A proposal reaching
for the harness or a safety declaration is not a candidate about which the
owner should be asked to form a view.

**5. Gate spans are emitted through the injected `Tracer`**, never a
directly-constructed exporter — the same reason nodes receive a tracer via
`Services`. A gate that built its own would be reaching outside its inputs,
and `aef/harness/` would acquire a vendor dependency.

## Consequences
- 25 tests. Altering, removing, reordering, and truncating the ledger are
  each tested and each detected.
- `merged_versions()` gives the bisection index M10 acts on: a regression
  found in production walks back to the change that introduced it without
  guesswork.
- The pipeline runs unchanged with no tracer, so observability is additive
  rather than a dependency.
- **The ledger is tamper-*evident*, not tamper-*proof*.** Someone who can
  write the file can rewrite the whole chain from any point forward and it
  will verify. What the chain gives is that a *partial* edit — the realistic
  case, and the one an automated actor would produce — cannot pass. Making
  it tamper-proof needs an external anchor (a signature, or a copy the
  writer cannot reach), which is **not built here** and should not be
  assumed.

## Alternatives Considered
- **Plain append-only JSONL.** Rejected: it detects nothing, and the actor
  whose behaviour is being recorded is the one that could edit it.
- **Store the ledger in git and rely on commit history.** Rejected: a
  force-push rewrites it, and the harness must not depend on branch
  protection it does not control.
- **Sign each entry.** Deferred, and the genuine upgrade path — it needs key
  management this repo has no story for yet, and half a signing scheme is
  worse than an honest hash chain.
- **Put the diff first, with a summary above it.** Rejected: readers scroll
  to code. The ordering here is the mechanism, not decoration.

## Confidence
High on the chain properties, all directly tested. High that decision-first
ordering is right, though it is a claim about human behaviour rather than
something the tests can prove — the test only pins the ordering. Medium on
the escalation wording being genuinely answerable by a non-expert; that is
exactly the thing that cannot be verified without the actual owner reading
one.
