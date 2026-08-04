# ADR 0059: The adoption kit leads with what does not work yet

## Status
Accepted. Implements M13. Extends ADR 0034 (onboarding kit) and ADR 0040
(cross-harness entry files).

## Context
`aef adopt` emitted nine files and none of them mentioned the loop. A repo
adopting AEF got the scaffold and the autonomy contract, but no way to run
the self-rewiring pipeline and no statement of what it requires.

The failure mode that matters here is specific. A repo whose agents start
producing candidates against an **empty corpus** sees every one rejected —
correctly, because absence of evidence is not evidence of non-regression
(ADR 0050/0051). But to whoever is watching, that reads as *"the loop is
broken"*, not *"the loop has nothing to judge against"*. The first reading
leads to debugging the harness; the second leads to recording scenarios.

## Decision

**1. `LOOP.md` leads with what does not work, before how to run it.**
Order: nothing merges automatically → the three things the owner must supply
→ zones → how to run → how to stop. A document that opens with commands
invites someone to run them and conclude the system is faulty. Asserted by a
test on the ordering, not left to editorial discipline.

**2. The three owner obligations are named explicitly and each says what
happens if it is missing:**
- **A corpus** — without it G2/G3 refuse every candidate.
- **Observations** — without them every monitoring window reports unobserved,
  which correctly rolls every change back. Monitoring with no input is a very
  expensive way to revert.
- **Halt notification** — a halt fails a CI job, and if nobody watches that,
  nothing has told you.

**3. The emitted workflows carry the same trigger discipline as aef-core's**,
and the adoption tests assert it in the *target* repo, not only in this one.
`pull_request` / `pull_request_target` are absent, permissions are
`contents: read`, the gate checks out `main`, and `--state` points outside
the checkout. A trap that is only closed in the source repo is not closed.

**4. `corpus/README.md` says "Empty on purpose" in its first line.** An empty
directory with no explanation is indistinguishable from a broken install.

**5. Everything is never-overwrite**, consistent with the rest of `adopt`.

## Consequences
- `aef adopt` now emits **14** files: the onboarding kit (6), the
  cross-harness entry files (3), and the loop kit (5).
- The exact-set test switched from bare filenames to **relative paths** —
  the loop kit adds two files both called `README.md`, and a name-set would
  have silently collapsed them into one and still passed.
- 21 new adoption tests, including trigger-discipline assertions against the
  generated workflows.
- **The emitted workflows assume `main` and `pip install -e ".[dev]"`.** A
  repo with a different default branch or packaging must edit them. They are
  a starting point, not a drop-in, and `LOOP.md` does not pretend otherwise.

## Alternatives Considered
- **Emit a populated example corpus.** Rejected: it would be recorded against
  aef-core's demo agent, so it would gate the adopting repo against behaviour
  that repo does not have. A corpus that measures the wrong thing is worse
  than an empty one, which at least refuses honestly.
- **Enable the loop workflows on a schedule by default.** Rejected: they
  would run hourly against an empty corpus from the moment of adoption,
  producing a stream of failures before the owner has read anything.
- **Put the loop docs inside the existing `AGENT_INTEGRATION.md`.** Rejected:
  that file addresses the *agent*; `LOOP.md` addresses the *owner*, and the
  three obligations are things no agent can discharge.

## Confidence
High on the emitted content and its never-overwrite behaviour, all tested,
plus a real `aef adopt` run into a fresh directory. Medium on whether
`LOOP.md` actually prevents the "loop is broken" misreading — that is a claim
about how people read documents, and the test only pins the ordering, not the
effect. **Not claimed:** that an adopting repo can run the loop without
further work. It cannot: it must record a corpus, emit observations, and wire
a halt channel first, which is precisely what the document says.
