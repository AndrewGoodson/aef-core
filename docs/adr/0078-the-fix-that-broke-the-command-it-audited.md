# ADR 0078: The fix that broke the command it audited

## Status
Accepted. Phase 2 round 3 — the last unswept join, `proposer → workspace →
G0`. Six defects; **the first was introduced by ADR 0075, one round earlier,
and shipped to main.**

## The regression I shipped

ADR 0075 fixed a real problem: `cycle()` discarded a proposal's citations, so
the review report described a memory-grounded proposal as *"none
(control-cohort member)"*. The fix wrote them to the ledger:

```python
"grounded_in": list(proposal.grounded_in) if proposal else [],
```

`ledger.append` JSON-serialises `detail`. `Citation` is a frozen dataclass.

```
$ aef loop cycle --repo . --state ... --memory memory.jsonl
error: Object of type Citation is not JSON serializable
EXIT CODE: 1
```

**`aef loop cycle` could not complete a single proposal.** No gate ran. The
ledger was left holding a `proposed` entry with no verdict — a dangling
proposal in a tamper-evident chain — and an un-gated `loop/*` branch
accumulated per invocation. Exit 1 is `EXIT_REJECTED`, so CI read a
serialisation bug as *"this candidate is no good"*: the exact failure mode
ADR 0075 itself fixed on a different value, reintroduced two hours later.

The test I wrote to defend that wire was:

```python
assert "proposal=proposal" in inspect.getsource(cycle)
```

It asserts the wire is connected and never sends anything down it. Three
tests in that file are of this shape, and this is the price of the shape. A
source-string assertion is a comment the test runner checks — useful for
pinning a decision, useless for pinning behaviour. The replacement builds a
real `Proposal` with real `Citation`s and round-trips it through
`ledger.append`/`ledger.read`.

## The other five

**The proposer read the working tree; the branch is built from `base_ref`.**
So every un-proposed working-tree change was laundered into the candidate.
Observed: a rationale reading *"raising RETRY_BUDGET from 3 to 4"* against a
diff that also carried an `import os` nobody had reasoned about — which G0
then sized and scanned as part of the proposal. Now read via
`repo.show(base_ref, path)`: the same ref the diff is taken against, so the
artefact judged is the artefact proposed.

**Detached HEAD left the job on the candidate branch.**
`rev-parse --abbrev-ref HEAD` returns the literal string `"HEAD"` when
detached — which is the *normal CI shape*, since `actions/checkout` with a
ref or SHA detaches — so the restore was `git checkout HEAD`, a no-op. The
working tree kept an un-gated mutation, and the next cycle read it as its
starting point: cycle 2's rationale said 4→5 while its diff said 3→5. The
trust boundary itself held (gates read via `git show <ref>:<path>`), but the
artefact drifted from the reasoning about it.

**Ordinary Python turned the proposer off.** `find_constants` uses the AST;
`rewrite_constant` re-validates with a line regex that rejects a trailing
comment, a semicolon, or a parenthesised value — and `propose()` raises on
the first offender, so **one** such line made the proposer emit nothing for
the whole file, including for constants beside it that were perfectly
rewritable. `RETRY_BUDGET = 3  # how many attempts` is not exotic. The regex
now accepts and preserves a trailing comment, and `find_constants` returns
only what the rewriter can handle, so the two agree by construction rather
than by coincidence.

**A five-member cohort could be one distinct mutation.** `coerce_value`
moves an integer by at least one whole unit, so `RETRIES = 1` has about two
reachable mutations; the generator emitted five members anyway and G3's floor
counts **members**. Five copies of one mutation satisfied the floor and gave
the percentile a point mass — ADR 0063's shape, a guard that cannot
discriminate. Members are now distinct by construction, and a source that
cannot yield a distinct cohort **refuses** with a message naming the cause
and the fix. Refusing is honest: G2/G3 then decline for lack of evidence and
the candidate escalates, rather than being measured against a threshold that
means nothing. The cost is real and stated: an agent whose only tunable is a
small integer cannot be gated by G3 at all.

**G0 scanned a lossily-decoded string.** `GitRepo.show` decodes with
`errors="replace"`; the sandbox writes the workspace from raw bytes. So G0
and the runtime saw different source, and a file containing invalid UTF-8
passed G0 as clean and then failed to compile — surfacing as a confusing G1
error on a file G0 had just called safe. Not a security bypass: the allowlist
and forbidden-call names are pure ASCII, so replacement characters can
neither manufacture nor conceal one. It is a gate judging a different
artefact than the one that runs, which is enough. G0 now reads bytes and
decodes strictly, reporting an undecodable file as a violation.

## What the sweep found clean

Worth recording, since a dry result is evidence too. The workspace
round-trip is **exact** — `build_candidate_workspace` reproduced the
committed blob byte-for-byte across seven cases including invalid UTF-8 and
mixed line endings, with the detector validated against planted faults. The
control cohort **cannot** emit unparseable Python: 18,000 generated controls,
zero syntax errors, checked against a planted broken-syntax control.
`_materialise_base` calling `build_candidate_workspace` without a zone policy
is inert, because that call forces `entries=()` and the policy is only
consulted per entry.

## Consequences
- Adopters on ADR 0075's `main` must upgrade: `aef loop cycle` is broken
  there.
- A single-small-integer agent cannot be gated by G3 and now says so, rather
  than being gated against a meaningless threshold.

## Confidence
High on all six: each was reproduced by running, and each fix was re-run
against the failing case. **The honest caveat is about my own process, not
the code:** ADR 0074 asserted "verified end to end" of a change that
contained an unshipped-at-the-time defect, and ADR 0075 shipped one. Both
passed a green suite of 939 and 954 tests respectively. The tests that would
have caught either did not exist, and one of them I had written myself in the
weaker form the same day.
