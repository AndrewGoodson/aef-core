# ADR 0109: The trust boundary is the launcher, not the library

## Status
Accepted. **Corrects ADR 0047**, whose central mechanism claim was inaccurate.
0047 is not superseded — its `--no-renames`, blob-mode and sandbox-capability
decisions all stand and are unaffected.

## Context

ADR 0047 stated the property that makes self-coding survivable:

> "Every byte of gate code, corpus, eval suite, and CI configuration is read
> through `BaseRefHarness`, which resolves it at the base ref via
> `git show <base>:<path>`... there is **no code path** that reaches the
> branch's copy, so there is nothing to forget."

An independent 10-round bug hunt (`CODEX_BUGHUNT_REPORT.md`, round 10) reported
that claim false. The review of that work (`REVIEW_FINDINGS.md`, lens 1)
re-derived it rather than accepting it:

```
$ grep -rn "BaseRefHarness" aef/          # before the correction
aef/harness/trust.py:9:   through `BaseRefHarness`, which resolves it at ...
aef/harness/trust.py:38:  class BaseRefHarness:
```

Two hits, both its own definition. Every other reference in the tree was a test
or an ADR. **Nothing called it.** The loop imports its gates from the
already-running AEF package, exactly as any Python program does.

## Decision

**1. The boundary is trusted execution provenance, established by the launcher.**
`.github/workflows/loop-gate.yml` checks out `ref: main`, runs
`pip install -e ".[dev]"` from it, and only then fetches the candidate into
`refs/loop/candidate` as data. The gates that run are the ones installed from
`main`. That is the real mechanism, it is inspectable in the workflow file, and
it works.

**2. `BaseRefHarness` is a primitive, not the integrated loader.** It pins a
base commit and reads or materialises Zone B files from it. Its acceptance test
is honest about what it proves: a caller that goes through the primitive gets
the pinned copy even when the checked-out branch has rewritten that file. It
does not mediate reads it is never asked to make.

**3. A library cannot attest its own import provenance, and this ADR stops
claiming otherwise.** By the time `aef.harness` is imported, the decision of
*which* `aef.harness` was made. No code inside it can undo that. A local
launcher that imports AEF from a candidate checkout forfeits the property, and
the zone check is then the only thing left — which is precisely the arrangement
ADR 0047 argued against relying on.

**4. This is a deployment obligation for adopters.** `aef adopt` ships
`loop-gate.yml` for this reason. **A repo that drives the loop by any other
path — a local script, a different CI system — does not inherit the isolation
property and must establish equivalent provenance itself.** This is the single
most important sentence in this ADR for anyone adopting AEF.

## Why a new ADR rather than an edit in place

The correction was first made by editing 0047's body, with a dated block
quoting the original claim. That preserved the history honestly and is better
than a silent rewrite. Two things argued for recording it separately as well:

- **The index was left lying.** `docs/adr/README.md`'s one-line summary for
  0047 still read "Gates execute from the base ref... so a candidate that
  rewrites its own gate still faces the original" — the exact false claim. The
  index is what a reader consults first, and a correction buried in the body
  does not reach it. Fixed in the same commit as this ADR.
- **The repo's own convention.** 0044 supersedes 0041 "whose palette premise
  was disproved"; 0094 supersedes the security model of 0085 and 0088. The
  direct precedent is **ADR 0063**, a doc-vs-code audit that found one false
  claim among nineteen and was recorded as its own ADR rather than as an edit
  to the ADR it corrected.

An ADR edited to match the code reverses the direction of authority. Doing it
once, dated and quoted, is defensible; making it the habit is how a decision
record becomes a description of whatever the code happens to do.

## Consequences

- The isolation property is **verifiable by reading one workflow file**, which
  is a better place for it than a claim distributed across a library.
- The property is **conditional on how the loop is launched**, and that
  condition is now stated wherever it matters: this ADR, 0047's correction
  block, `trust.py`, and the G2/G4 gate docstrings.
- `BaseRefHarness` remains useful and tested — a caller that wants a pinned
  base-ref tree can have one. It is simply not load-bearing today.
- **Not claimed:** that the supplied workflow is the only correct launcher, or
  that it is sufficient against a compromised runner. It establishes provenance;
  container isolation (ADR 0105) is a separate control.

## Confidence

High that `BaseRefHarness` had no production call site — verified by grep
against the tree, twice, by two independent agents. High that the workflow
establishes what it claims — verified by reading the checkout/install/fetch
ordering in `loop-gate.yml`. High that no gate behaviour changed in the
correction — verified by parsing both versions of every touched module,
stripping docstrings, and comparing ASTs: `g2_outcome.py` and
`g4_separation.py` came back identical.

Medium on how many *other* claims in the ADR corpus have aged out of true the
same way. This one was found because an independent agent went looking. Only
0047 was checked closely; 109 ADRs were not.
