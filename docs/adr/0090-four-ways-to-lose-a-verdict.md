# ADR 0090: Four ways to lose a verdict

## Status
Accepted. The remaining findings from the adversarial round that produced
ADR 0088 and ADR 0089. Each is a place where the system reached a conclusion
and then failed to record it, misclassified it, or corrupted the evidence it
was drawing it from.

## 1. A gate that raised took the whole run down

`_run_traced` did not catch. So **any** exception from **any** gate escaped
`run_pipeline`, escaped `gate()`, escaped `cmd_gate`, and left the process on
a traceback — with **no `GATED` ledger entry at all**.

The candidate got no verdict, and a tamper-evident audit trail acquired a
hole that nothing recorded. Candidate-triggerable: a graph whose factory
fails to load reaches `G2ExecutionError` this way, and the seam-hunter found
it that way.

A gate that raises now FAILs, with the exception type and message in the
reason. **FAIL, not skip:** a gate that could not judge has not cleared the
candidate. `Exception` and not `BaseException`, because a `KeyboardInterrupt`
is the operator stopping the run and swallowing that would make the loop hard
to stop — which `KillSwitch` exists precisely to avoid.

## 2. A partial marker read as a parse error, not a forgery

`str.count` is non-overlapping. A candidate writing
`RESULT_MARKER_PREFIX + nonce` **without the suffix** let the runner's own
leading `\x00` complete a match: the count stayed at 1 while two partial
markers were present, and the payload read was the runner's marker text
rather than JSON.

That surfaced as `SuiteError: invalid JSON` — an ordinary bad-candidate
outcome — for what is agent code reaching for the evidence channel. The
prefix is now counted too, and more than one is a security event.

## 3. Replay rewrote the record it was verifying

ADR 0087 stopped the executor handing live state to a node, and left
`ReplayEngine` doing exactly that: deterministic re-execution passed
`record.input_state` — the live recorded object — straight to `node.fn`.

A node that mutates its input therefore rewrote the record replay was
checking. Worse, **the chain check then passed only because replay had
reproduced the mutation into its own copy** — a verification validating its
own side effect.

Same fix, same fallback as ADR 0089: deep-copy where possible, share where
not.

## 4. A `--config` that could not apply said nothing

`--repo`, `--state` and `--workdir` are all filesystem paths, so an absolute
`--config` is the natural thing to type. `git show <ref>:/abs/path` finds
nothing, so the configured policy was **silently discarded** and the run
continued deny-by-default, looking configured.

Two more silent paths: a config that exists only on the candidate branch, and
one that fails schema validation, both returned quietly.

Deny-by-default was the right *value* and silence was the wrong *delivery* —
an invalid config was indistinguishable from a deliberately restrictive one.
All three now raise `PolicyConfigError`, surfaced by every loop command.

Two of my own ADR 0082 tests pinned the silent behaviour and were rewritten,
with the reasoning recorded in them.

## The thread

All four are the same shape: **the system knew something and the operator did
not.** A verdict that never reached the ledger, a security event filed as a
parse error, a check that corrupted its own evidence, a policy that quietly
did not apply.

None of them made a bad candidate pass. Every one of them made the record of
what happened wrong, and this repo's whole argument for being safe to run
unattended rests on that record.

## Confidence
High: each was reproduced by running before the fix and re-run after, with
controls — a raising gate fails while an interrupt still propagates, an
honest deterministic replay still verifies, a relative in-repo `--config`
still loads.

**Not claimed:** that the gate-raise fix is free of consequences. Converting
every exception to FAIL means a genuinely broken gate now rejects candidates
instead of announcing itself loudly, and the reason string is the only signal
distinguishing the two. An operator seeing repeated `gate raised ...` reasons
is looking at a broken harness, not a bad proposer, and nothing yet
aggregates that for them.
