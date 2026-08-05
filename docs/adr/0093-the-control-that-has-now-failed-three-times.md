# ADR 0093: The control that has now failed three times

## Status
Accepted for what it fixes. **Escalated, not resolved, for what it does not.**
Round 5 of five. Two independent sweeps, agreeing on the critical finding.

## Read this first

`getattr(module, "os")` defeats ADR 0088 completely. Four lines of legal Zone
A code — no forbidden import, no forbidden attribute, **zero G0 findings** —
reconstitute the ADR 0085 attack and pass all six gates on a broken agent.

```
CONTROL literal attr   findings=1 REJECTED
getattr                findings=0 PASSES G0
getattr "o"+"s"        findings=0 PASSES G0
vars()                 findings=0 PASSES G0
__dict__               findings=0 PASSES G0
```

End to end through the real `gate()`, same candidate, one variable changed:

```
[control] disposition = reject      G3: fail
[attack]  disposition = escalate    G0 pass G1 pass G4 pass G5 pass G2 pass G3 pass
```

**I am not fixing this by adding `getattr` to a denylist.** That is the same
move that failed in ADR 0085 and again in ADR 0088, and the next bypass is
`vars`, then `__dict__`, then `operator.attrgetter`, then something I have
not thought of — which is precisely the sentence ADR 0088 already had to
retract.

The sequence, stated plainly:

- **ADR 0085** framed the evidence channel and claimed three independent
  layers. One was `sys` being unreachable.
- **ADR 0088** found `sys` reachable through `aef.harness`, denied the
  import and the attribute, and said "low on completeness".
- **ADR 0093** finds the attribute denial reads syntax while the interpreter
  offers the same reach by string.

Three attempts, three defeats, each by a smaller change than the last. The
honest reading is not that the fourth patch will hold. It is that **static
allowlisting over a shared interpreter is the wrong instrument**, and the
decision about what replaces it is the owner's.

The code comment asserting closure has been removed and replaced with what is
actually true.

## What this ADR does fix

**A build command that forks was rejected on any developer machine.**
`SandboxPolicy.max_processes=256` was fed to `RLIMIT_NPROC`, which is a
**per-UID total**, not a per-run allowance. On a laptop with 538 user
processes, every candidate whose green bar shells out to `git`, `pytest -n`,
`npm` or `docker` failed with `BlockingIOError` — reported by G1 as an
ordinary build failure. ADR 0069's shape again: invisible in a container,
fatal outside one. The default is now unset; an operator who wants a ceiling
sets one knowing what it counts.

**The timeout did not kill what two comments said it killed.**
`subprocess.run(timeout=...)` calls `Popen.kill()` — the direct child only —
and `_preexec` calls `setsid()`, so descendants sat in a group nothing ever
signalled. A grandchild outlived the timeout by six seconds and wrote a
marker after the gate reported finished. Now `Popen` holds the pid and the
group is killed. My first attempt at this fix was a no-op — `TimeoutExpired`
carries no `pid` — and only running it revealed that.

**ADR 0091's default durability re-killed what ADR 0089 made legal.**
`InMemoryDurabilityBackend` JSON-encodes every checkpoint, so a
`threading.Lock` or open handle in `working_memory` — legal since ADR 0089 —
raised `PydanticSerializationError` on the first super-step, which
`scenario_runner` turned into a uniform 0.0. The ADR 0075/0079/0089 shape a
**fourth** time. The gate's throwaway backend no longer serialises: nothing
reads those checkpoints, so encoding them bought a constraint and no
capability.

**A harness crash was reported as a candidate regression.** `run_scenario`
writes a `failure` field explaining why a scenario produced nothing, and
`_parse` discarded it — so an unserialisable value surfaced as *"5
previously-passing scenario(s) no longer pass"* with a fabricated
`error_count: 1`. The diagnostic is now carried.

**ADR 0090's verdict-losing hole was still open on the one path that
executes candidate code.** `_gates_with_evidence` sits *between* the two
`run_pipeline` calls, so `_run_traced`'s raise-to-FAIL conversion never
covered it, and its handler caught only `SuiteError`. A `KeyError` from
`_parse` escaped `gate()` and left a `PROPOSED` entry with no verdict — the
exact hole ADR 0090 §1 says was closed.

## Recorded, not fixed

- `--agent-root ""` makes all of Zone C agent-writable. Operator input, not
  candidate input, so a footgun rather than an escape — and the existing test
  uses that exact value and asserts only the Zone B half.
- G0's attribute denial false-positives on ordinary code: `config.os`,
  `args.argv`, `registry.modules`. No shipped scaffold trips it; an adopter
  whose domain object has such a field is rejected with a security-flavoured
  message. Fixing this properly is entangled with the escalation above.
- A case-variant Zone B path (`AEF/harness/x.py`) is denied but not raised as
  a security event, so it does not halt the loop on a case-insensitive
  filesystem.
- `RuleBasedJudge.score` is unbounded and agent-written. Blast radius traced
  as nil today — nothing gates on it — but it is a number the measured party
  writes.
- `DEFAULT_RUBRIC` now exists in three places, which ADR 0091 was supposed to
  be about.

## Confidence
High on each fix: reproduced before, re-run after, controls included — and
one of them was a no-op on the first attempt, caught only by running it.

**The completeness claim is the point of this ADR, and it is negative.** Five
rounds have run and none were dry. The rate of finding has not fallen. Three
of tonight's defects were introduced by tonight's own fixes. I do not believe
another round of the same method converges, and the stopping rule agrees.
