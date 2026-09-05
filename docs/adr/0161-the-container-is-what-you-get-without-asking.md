# ADR 0161: The container is what you get without asking

## Status
Accepted. UPGRADE_LOOP's S5, BEYOND_90's J3. Model: Opus (session default).
Zero live model calls.

## Context

BEYOND_90's J3 asks for the container to be **the default for the shadow
when a runtime and image are available, with an explicit, logged, named
fallback when they are not** — closing the trust case's second load-bearing
finding, that a shadow node doing direct file I/O is not contained by the
tool policy.

J0 (ADR 0151) scored dimension 4 at 14/15 and gave one deduction. Half of it
was this: `test_the_in_process_shadow_bypass_is_still_real_when_opted_into`
"concedes an uncontained path still exists when opted into".

## Reproduction, before anything changed

`<scratch>/repro.py`, run against this worktree
(`aef.__file__` verified to be the worktree's own):

```
=== ARM C: ShadowRunner(incumbent, candidate) -- no session, no flag ===
C: refused -> UncontainedShadowError: shadow execution runs a candidate's
   code on LIVE input, and an in-process shadow contains only its T...

=== ARM A: uncontained=True, node writes /var/.../tmprmtgc94l/escaped-to-host-A ===
A: marker exists on the HOST: True
A: contents: 'the shadow wrote this'
A: observation.contained = False

=== ARM B: contained, runtimes=('docker',) ===
B: marker exists on the HOST: False
B: observation.contained = True
B: divergence.candidate_failed = "NodeEvaluationError: FileNotFoundError:
   [Errno 2] No such file or directory: '/var/.../escaped-to-host-B'"
```

**Arm C is the finding, and it is not the one J3 expected.** ADR 0105 had
already made containment the default *by refusal*: the constructor will not
build without a container session. So there was no uncontained-by-default
path to close at the constructor.

What was actually wrong is Arm C read against Arm B. On this box — a running
daemon, `aef-worker:test` built — the caller that asked for nothing got the
same flat refusal as a caller with neither. **Nothing here ever *provided*
the container.** Every contained run in the repo hand-builds
`contained_candidate_graph`, and the one-line way past the refusal is
`uncontained=True`. Containment was the default the way a door is locked when
nobody has a key: the path of least resistance was the bypass.

## The decision

**`shadow.containment: auto` is the default, and `auto` resolves rather than
refuses.** `resolve_containment` looks for a runtime, verifies its isolation
in both directions (`container.py`'s existing probe, which measures rather
than declares), and hands back a decision. `shadow_for` turns that decision
into a `ShadowRunner` whose candidate runs inside the container.

**`auto` does not fall back.** This is where J3's wording and the code as it
stands disagree, and the disagreement is resolved in favour of the stronger
control:

- J3 asks for "an explicit, logged, named fallback when they are not
  [available]". It was written against a repo where the shadow's default was
  uncontained, so a fallback would have been a strict improvement.
- Against ADR 0105's refusal it is a strict *weakening*: today an operator
  with no runtime cannot run a shadow at all; an automatic fallback would let
  them, and would put the weaker mode back on the path of least resistance
  after this ADR spent its whole argument taking it off.
- HARD-STOP gate 2 says stop rather than weaken. The increment is deliverable
  without weakening, so this is not a full stop: **the fallback is kept, named
  and logged, and reached only by an owner writing it in `aef.yaml`.**

Three modes, in `aef/config/schema.py::ShadowConfig`:

| `shadow.containment` | runtime + image present | absent |
|---|---|---|
| `auto` (default) | contained | **refuses**, naming which half was missing |
| `fallback` | contained | in-process, announced and ledgered |
| `off` | in-process | in-process, announced and ledgered |

`shadow.image` has no default, because this repo has no image it can ship —
the worker image must contain the adopter's own `aef` (trust case §2.1). An
unset image under `auto` is a refusal that says `shadow.image` is unset, not
a silent downgrade.

## The reproduction, after

`<scratch>/repro2.py`:

```
=== AFTER / DEFAULT (shadow.containment: auto, runtime + image present) ===
  mode              : auto
  contained         : True
  reason            : contained by docker with image aef-worker:test; isolation verified
  runtime.verified  : True
  runner.contained  : True
  resolve+run took  : 0.98s
  HOST marker exists: False   <-- was True before this increment
  observation.contained: True
  candidate_failed  : "NodeEvaluationError: FileNotFoundError: ..."
```

The same escaping candidate, the same box, no arguments beyond the image: the
write that landed on the host in Arm A does not land.

## The fallback wording, verbatim

Both named causes are module constants so a test can pin the exact words an
operator sees — a refusal that misnames its own cause sends them to fix the
wrong thing (ADR 0074).

```
no container runtime found
no container image configured (shadow.image is unset)
image unavailable: <the runtime's own reason, verbatim>
owner opted out in aef.yaml: shadow.containment: off
```

Printed on stderr:

```
aef: shadow containment FELL BACK to in-process by owner choice — no
container runtime found. The candidate's nodes run in this process: the
policy engine denies its TOOL CALLS and nothing contains a direct file write
(trust case section 2.1). Every observation records contained=False and the
whole report is downgraded for all of them.
```

And the refusal under `auto`, which names the way out because a refusal an
operator cannot act on gets routed around:

```
UncontainedShadowError: shadow containment is unavailable: no container
runtime found. shadow.containment is 'auto', which contains the candidate or
refuses — it does not run it uncontained, because an in-process shadow
contains only its TOOL CALLS and a node that opens a file directly is outside
the policy engine (trust case section 2.1). Build a worker image and set
shadow.image, or set shadow.containment: fallback to accept an uncontained
shadow here — that choice is recorded in the ledger.
```

## Not only stderr

A stderr line from last Tuesday is not an audit trail. `EventKind.CONTAINMENT`
joins the ledger, and `record_containment_decision` writes **both** directions
— recording only the fallbacks would make "the shadow ran contained" and "no
shadow ran at all" the same absence, which is the shape `ShadowReport.contained`
already refuses over zero observations.

```
kind=containment summary=shadow containment: NOT contained (no container runtime found)
detail={'containment': {'contained': False, 'image': 'aef-worker:test',
        'isolation_verified': False, 'mode': 'fallback', 'owner_opted_out': True,
        'reason': 'no container runtime found', 'runtime': None},
        'security_event': True}
```

`security_event` is not read by anything in `shadow.py`. It is the key
`aef.harness.monitoring.build_digest` counts, so an uncontained shadow appears
in the owner's weekly digest without anyone remembering to go looking. That
seam is under test (`test_the_digest_counts_an_uncontained_shadow_as_a_security_event`)
because a detail key nobody counts is a stderr line with extra steps.

## The one production opt-out, and why the AST test now allows exactly one

`shadow_for`'s fallback branch passes `uncontained=True`. It is the only such
call in `aef/`, and the AST scan that used to require zero now requires
**exactly this one** — matched by file *and enclosing function name*, so it
survives edits above it and cannot grow silently. The allowance is paid for by
a second test: under the default mode, `shadow_for` raises before constructing
any runner, even when handed an `in_process_candidate` it could have used, and
writes no ledger entry — a refusal is not a run.

Considered and rejected: giving `ShadowRunner` a second field (a
`ContainmentDecision`) so the literal `uncontained=True` would vanish from
`aef/`. That is two spellings of one security decision with nothing checking
they agree — the drift ADR 0091 records, and this module's own docstring
already cites it against exactly that move. One mechanism, one allowlisted
call site, both under test.

## What the trust case's second finding now says

§2.1's "Two things remain" paragraph said an adopter without a worker image
"must opt out explicitly". That was true and incomplete: it did not say that
an adopter *with* an image had to hand-build the container, which is the half
that made the bypass convenient. The paragraph now states the resolver, the
three modes, and that the opt-out is recorded in the ledger as a security
event. Reason #2 of the recommendation was already marked spent by ADR 0105
and is unchanged — this ADR does not revive it, and does not claim any of the
other three reasons has moved.

## Also fixed: a control that cried wolf

`test_closing_the_session_leaves_no_container_running` diffed the **whole**
daemon's `docker ps`. Two other workers on this box tripped it, and a third
occurrence is recorded in ADR 0154's own green-bar note as "one unrelated
flake". Reproduced (`<scratch>/flake.py`), with a foreign container started
between the two calls:

```
OLD (unfiltered): survived={'d1abb74c744e'} -> FAILS (spurious)
NEW (name=aef-worker-): survived={} -> passes
```

Now filtered to the `aef-worker-` name prefix `isolated.py` assigns. It still
catches a real leak — mutation M5 below — and no longer catches other people's
work. A control that cries wolf gets ignored, which is the same end state as
not having it.

## Mutations: 5 perturbed, 5 detected

Each restored from a shasum-verified byte backup, hashes re-checked after.

| # | mutation | result |
|---|---|---|
| M1 | `auto` falls back instead of refusing | CAUGHT — 5 failed |
| M2 | an uncontained run is not a `security_event` | CAUGHT — 3 failed |
| M3 | the config default becomes `fallback` | CAUGHT — 1 failed |
| M4 | `shadow_for` never containerises | CAUGHT — 1 failed |
| M5 | `close()` leaves the worker container running | CAUGHT — 1 failed |

M5's first attempt inserted a `def` into an import block and the test failed
in 0.46 s, which is what a `SyntaxError` looks like rather than what a leaked
container looks like. Re-done against `NodeWorkerSession.close`'s
`_force_remove` call; the failure is now the assertion, quoting the surviving
container id (`{'30f67679c317'}`), and the leaked container was cleaned up by
hand afterwards. A mutation whose failure has the wrong cause proves nothing
about the test.

## What this does not claim

- **Shadow execution still has no production caller.** `shadow_for` is the
  API a caller should use, and on this box it contains; nothing in `aef/`
  invokes shadow execution yet, exactly as before this ADR. What changed is
  which outcome an integrator falls into, not that the loop now shadows.
- **The container is not the policy engine.** It stops a node reaching the
  host. `assert_shadowable` still refuses a MUTATING candidate, contained or
  not, and this ADR does not soften it.
- **The workspace is still writable**, deliberately, and it is a host
  directory. §2.1 has always said so and still does.
- No `PolicyEngine`, gate, or Tier-1 code was touched. `git diff --stat`
  covers `aef/harness/shadow.py`, `aef/harness/ledger.py` (one enum member),
  `aef/config/{schema,factory}.py`, and three test files.

## Consequences

Dimension 4 moves 14 → 15. The 14 was written as "One point off: shadow
containment is opt-in"; it is not, and the half of J0's deduction that read
the old test name as a concession is answered by a test that states both
halves of the truth — the bypass is real under the opt-out, and the opt-out
is an owner statement that is announced and ledgered.

J0's other half — that the adversarial-round record is a prose grep — is
answered by discoverability rather than by a new mechanism: A4 and A5, the two
attacks that BROKE IT, are each re-executed by a test
(`test_promotion_safety.py::test_a_mutating_candidate_is_refused_before_any_live_request`
and `test_contained_shadow.py::test_the_bypass_is_still_real_under_the_opt_out_and_is_announced`),
and the grep test's docstring now names them, because BEYOND_90's rule for
evidence a reviewer could not find is to make it discoverable, not to overrule
the reviewer.
