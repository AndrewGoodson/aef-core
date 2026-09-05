# ADR 0190: The ingestion path opens — the recorder records, and the re-check can reproduce a containment fact

## Status

Accepted. Fix worker **L2** of `UPGRADE_LOOP.md`, closing all three findings
ADR 0163's pilot reported and left for a fix worker: **F-M6-1**, **F-M6-2** and
**F-M6-3**, plus two observations that pilot made and did not act on.

Model: **`claude-opus-5[1m]`** (session default). **ZERO live model calls** —
every reproduction and every arm below runs a local `command` provider whose
argv is `/bin/echo`, or a stub in-process. M6 proved all three arms could be
priced offline; this worker priced the fixes the same way.

The headline, stated once and then evidenced: **before this, no run of any `aef
migrate`-generated prompt-agent graph had ever been harvestable, on any repo, by
any invocation.** `aef run --record-runs` -> `aef loop harvest` is the leg the
trust case's criterion 1 names, the leg the generated nightly workflow is built
around, and the leg the pilot ran on five real objectives and got `0 promoted, 5
REJECTED` from. It works now, end to end, and
`tests/cli/test_prompt_repo_acceptance.py::test_a_recorded_production_run_can_be_harvested_into_the_corpus`
— M6's strict xfail — is the assertion rather than the pin.

---

## F-M6-1 — `aef run --record-runs` recorded no model calls

### Reproduced

The whole documented sequence through the real CLI, on the synthetic prompt
repo `tests/cli/test_prompt_repo_acceptance.py` builds, with `model_provider.impl:
command` driving `/bin/echo`:

```
$ python scratchpad/w/l2/repro.py
== aef run --record-runs
   exit=0
   wrote ['e8f0d6ec-65fc-48ef-be3c-d7254ab4191e.json']
   model_calls=[]
   recorded prompt_agent__containment = {'isolation': ['no_project_context',
     'no_tools', 'single_turn', 'system_role'], 'persona_role': 'system',
     'provider': 'command'}
== aef loop harvest --include-successes
   exit=0
   promoted 0 run(s) to the train split
     1 REJECTED, did not re-execute deterministically: e8f0d6ec-…
```

`model_calls=[]` is the defect and `1 REJECTED, did not re-execute
deterministically` is the symptom — the verdict a flaky run gets, for a run that
reproduces exactly. `RecordedRun.model_calls`' own docstring had named this
outcome in advance: *"a correct-looking rejection for the wrong reason"*.

### Fixed

`aef/cli/run.py` now captures model calls the way `aef loop record` and `aef loop
bootstrap` do — **the same recording `CassetteProvider`, one recorder, ADR
0149's rule** — and writes `recording.recorded` onto the `RecordedRun`.

Two decisions inside that:

- **Wrapped only when the run is being recorded**, unlike `recorder.py` which
  wraps always. Without `--config` there is no provider to wrap, and this
  module's contract — stated in its own docstring — is that
  `require_model_provider()` then raises `ServiceNotConfiguredError` rather than
  reporting a cassette miss. A plain `aef run` is byte-for-byte the run it was,
  and `test_a_plain_run_is_unwrapped_and_unconfigured_runs_still_refuse` pins
  both halves.
- **The containment record now says `provider: 'cassette'`** on this path, where
  it said `provider: 'command'` before. That is ADR 0182's **open item 1** — the
  recording wrapper masks the provider name in the containment record — reaching
  one more path rather than a new defect, and the fix belongs where
  `CassetteProvider` sets `name`, which is not this worker's file. It is
  harmless to the verdict because recording and replay now say the same word,
  and §F-M6-2 says what was done so that it stays harmless when 0182's item is
  closed.

## F-M6-2 — the re-check had no provider, so it could not reproduce a containment fact

### Reproduced

With the cassette supplied by hand the same run is **still** rejected, and the
divergence is one field. Three arms, one variable each, all offline:

```
$ python scratchpad/w/l2/repro_arms.py
== arm 0 - as shipped (`aef run --record-runs`)
   promoted 0 run(s) to the train split
     1 REJECTED, did not re-execute deterministically: e8f0d6ec-…

   captured 1 model call(s) by hand

== arm 1 - + the cassette the recorder never wrote
   promoted 0 run(s) to the train split
     1 REJECTED, did not re-execute deterministically: e8f0d6ec-…

   recorded vs re-executed, the containment key:
     recorded    prompt_agent__containment = {'isolation': ['no_project_context',
       'no_tools', 'single_turn', 'system_role'], 'persona_role': 'system',
       'provider': 'cassette'}
     re-executed prompt_agent__containment = {'isolation': [],
       'persona_role': 'unknown', 'provider': 'cassette'}
   traces equal: False

== arm 2 - + the provider's declared isolation (patched in THIS process)
   promoted 1 run(s) to the train split

corpus after arm 2: ['manifest.json', 'train/e8f0d6ec-….json']
```

That is M6's result reproduced independently, on a different repo, with arm 2
priced by a shim that declares an isolation set and **answers nothing** rather
than by handing the re-check a live provider.

### The decision: (a), and why (b) is unsound

M6 posed two ways out.

**(a) The re-execution reproduces the ORIGINAL provider's declaration**, carried
on the recorded run and replayed. **Chosen.**

**(b) The trace comparison ignores `*__containment` keys.** Rejected.

The argument for (a) is not that it is more convenient. It is that (b) deletes a
recorded fact from the definition of *"behaviour unchanged"*, which is the
control ADR 0119 rests on. Under (b), a run recorded under a provider that
enforced `no_tools` and a re-execution that checked nothing about tools would
compare equal, and the scenario would enter the corpus carrying a containment
claim nothing had re-verified. ADR 0169 exists precisely because a containment
sentence was **stamped** rather than evidenced; (b) would re-stamp it one layer
down, in the one place that is supposed to be checking.

The objection to (a) is worth stating in full, because it is ADR 0169's own
words: `CassetteProvider.isolation` returns the empty set with no inner
provider, and the ADR says inventing the absent provider's properties "is the
failure mode ADR 0169 exists to close". The answer is that (a) invents nothing.
0169's rule is that a containment claim must never be **inherited unverified**.
The set replayed here was *observed* — by the recorder, at capture time, from
the provider object that actually answered — and stored on the run as data.
Replaying a recorded observation is the opposite of manufacturing one. What
would be unsound, and what is not done, is `CassetteProvider` reporting a set of
its own, or a set defaulted from config.

### Fixed

- `RecordedRun` gains `provider_isolation: tuple[str, ...]` — the provider's
  declaration, sorted, captured at recording time — and `provider_name: str`.
  Both default to `()`/`""`, so **every legacy recorded run loads and behaves
  exactly as it did**: it declares nothing, the replay declares nothing, both
  sides agree.
- `persona_role` is deliberately **not** stored beside it. It is
  `persona_role(isolation)` and nothing else, and a second copy of a derived
  value is a second thing that can disagree.
- `harvest._reexecution_services` builds the replay cassette over
  `_RecordedIsolation`, a `ModelProvider` that carries the recorded declaration
  and whose `complete` **raises**. Nothing live is reachable, which is the
  property the re-check exists to have: *"a harvest that reaches the network to
  decide whether a run is deterministic has already lost the property it is
  checking."*
- `provider_name` is carried for forward-compatibility rather than display.
  Today `containment["provider"]` is `'cassette'` on both sides and matches by
  accident. The day ADR 0182's open item 1 is closed — `CassetteProvider.name`
  forwarding its inner's — recording would say `'command'`, and a replay shim
  that named itself would reopen F-M6-2 in a new spelling. Recorded, the shim
  answers with the same name the recording had.

### After the fix, the same three arms — and no monkeypatching left

Arm 2 in ADR 0163 had to patch `harvest._reexecution_services` in-process. It
does not any more: all three arms are now the recorded run with fields removed,
because the missing piece became data.

```
$ python scratchpad/w/l2/three_arms_after.py
the run `aef run --record-runs` wrote: model_calls=1,
  provider_isolation=['no_project_context', 'no_tools', 'single_turn',
  'system_role'], provider_name='command'

== arm 0 - the run the OLD recorder wrote (no cassette, no declaration)
   promoted 0 run(s) to the train split
     1 REJECTED, did not re-execute deterministically: 8d468601-…
== arm 1 - + the cassette the recorder never wrote
   promoted 0 run(s) to the train split
     1 REJECTED, did not re-execute deterministically: 8d468601-…
== arm 2 - + the provider declaration the re-check never had
   promoted 1 run(s) to the train split

corpus after arm 2: ['manifest.json', 'train/8d468601-….json']
```

And end to end through the CLI, which is the sentence that was false on every
repo until now:

```
$ python scratchpad/w/l2/repro.py            # after the fix
== aef run --record-runs
   model_calls=[{'key': '05d0631f23c5…', 'request': {…}, 'result': {…}}]
== aef loop harvest --include-successes
   exit=0
   promoted 1 run(s) to the train split
```

### The control is exactly as strict as before

`test_a_declaration_the_replay_cannot_reproduce_is_still_rejected` takes a
recorded run, changes only its declaration — a persona that went out in the
system turn, replayed as one that went out in the user turn — and asserts
`rejected_nondeterministic == ("pa-3",)`. That is the case option (b) would have
admitted silently. ADR 0119's *"admit only if behaviour is unchanged"* still
compares the containment fact; it now compares it against something that can
reproduce it.

## F-M6-3 — `cycle --runs` was a silent no-op without `--module`

### Reproduced

Two invocations one flag apart, both `--no-memory` so neither can reach a model:

```
$ python scratchpad/w/l2/repro_m63.py
=== arm A: --entrypoint only (no --module)
    preflight: 4 of 6 obligation(s) unmet …
    ledger verified: 0 entr(ies)
    no memory store configured: nothing to learn from, no candidate
  cycle verdict: … (--no-memory was passed: this cycle could not propose)
  EXIT=0
  harvest line present: False        <- a runs directory was given

=== arm B: the same, plus --module
    …
    promoted 0 run(s) to the train split
      1 passed, not promoted: e8f0d6ec-…
  EXIT=0
  harvest line present: True
```

### Fixed

`_require_module_for_runs` refuses `--runs` without `--module`, before anything
that looks like work, naming both flags and saying what the missing one is for.
After:

```
=== arm A: --entrypoint only (no --module)
  stderr: error: `loop cycle` was given --runs but no --module, and --runs does
    nothing without it. The harvest leg needs a graph OBJECT to re-execute each
    recorded run against, and this command builds one from --module only —
    --entrypoint is read by the gates' scenario runner, in a subprocess, and
    never becomes the graph the harvest leg is handed. …
  EXIT=3
```

Refusing rather than deriving a module from `--entrypoint`: the two flags do not
have to name the same graph, and guessing which the owner meant is how a run
gets harvested against the wrong entrypoint — the very thing the next section
closes.

**`EXIT_ERROR` (3), not `EXIT_USAGE` (2), and this is a judgement call worth an
owner's eye.** Under the loop's exit vocabulary (0 verdict / 1 REJECTED / 2
HALTED / 3 ERROR, ADR 0182's K3-1) the rendered nightly workflow gives 3 its own
summary — *"fix the invocation"* — while 2 shares its number with a halt. This
is an invocation to fix, not a halt. The two refusals immediately above it in
`cmd_cycle` return `EXIT_USAGE`; **unifying the three is ADR 0182's own open
item 3 and remains an owner's decision, not a fix wave's.**

`aef loop run` has the identical `graph = load_graph_reference(args.module) if
args.module else None` line and the same `--runs` flag. It is **not** changed
here — outside this worker's files — and is named in the report.

## M6's five real runs, through the fixed leg — 5 of 5 promoted

The arms above run a `command` provider driving `/bin/echo`. This section does
not: it uses the **five real recorded runs the pilot produced**, from three real
marlin personas, answered live by `claude_code` under the operator's harness
login. Still zero live model calls — nothing is re-requested.

```
$ python scratchpad/w/l2/pilot_runs.py
5 real recorded run(s) from the M6 pilot
   22a5f0ec  graph=marlin-accela    model_calls=0  provider='claude_code'
     isolation=['no_mcp','no_project_context','no_tools','single_turn','system_role']  answer=3843 chars
   491c4102  graph=marlin-source    model_calls=0  … answer=6482 chars
   7d10629e  graph=marlin-source    model_calls=0  … answer=3140 chars
   999d7f25  graph=marlin-reviewer  model_calls=0  … answer=4270 chars
   9c48f5c9  graph=marlin-accela    model_calls=0  … answer=3324 chars

== arm A - the five run files exactly as the pilot wrote them
   marlin-accela:   promoted 0 run(s); 2 REJECTED, did not re-execute deterministically
   marlin-reviewer: promoted 0 run(s); 1 REJECTED, did not re-execute deterministically
   marlin-source:   promoted 0 run(s); 2 REJECTED, did not re-execute deterministically

== arm B - the same five, as the FIXED recorder would have written them
   marlin-accela:   promoted 2 run(s) to the train split
   marlin-reviewer: promoted 1 run(s) to the train split
   marlin-source:   promoted 2 run(s) to the train split

corpus scenarios written by arm B: 5
```

**Arm B is not a simulation of the fix; it is the fix, fed inputs read out of
the pilot's own artefacts.** Each run is re-executed through the same recording
`CassetteProvider` `aef/cli/run.py` now uses, over a provider that declares
**the isolation set that run's own containment block recorded** —
`['no_mcp','no_project_context','no_tools','single_turn','system_role']`, five
elements, `claude_code`'s real declaration, not the stub's three — and answers
with **the model's own words, read out of that run's trace**. Nothing is
invented and nothing is requested. What arm B does not reproduce is the network
call; what it does reproduce is every input the determinism re-check reads.

**Arm A is the honest other half: the fix does not retro-repair an artefact.**
Those five files were written by the old recorder, so they carry no cassette and
no declaration, and the fixed harvest rejects them exactly as the pilot's did —
five for five, split across the three graphs, which is also the first
demonstration of the `graph_id` filter on real data (each graph re-executes only
its own runs). Getting the pilot's *files* into a corpus means re-running `aef
run --record-runs`, which costs live calls.

This is the artifact ADR 0164's clause (a) asks for, one step short of the
command that would produce it live.

## Two observations from the pilot, acted on

### `harvest` re-executed other graphs' runs against this one's entrypoint

ADR 0163 §6's third observation, reported without a reproduction of harm:
`harvest()` iterated the runs directory with **no filter on `run.graph_id`** and
stamped each promoted scenario with the run's own id while having re-executed it
against the graph named on the command line. On the pilot it was masked — a
foreign run missed the cassette and was rejected as flaky — *and the masking was
F-M6-1's doing*, so closing F-M6-1 would have unmasked it in the same commit.

Filtered now, before the determinism re-check (re-executing a foreign run is the
thing being prevented, not a cheaper way to detect it), and **reported**:

```
promoted 1 run(s) to the train split
  1 recorded from another graph, not re-executed here: theirs-1
```

### `digest` printed two numbers and drew no line between them

`Production runs recorded: 5` and `Scenarios added to the corpus: 0`, side by
side, with nothing said — and the existing warning fires only when the count is
**zero**, which is advice the pilot had already followed five times. The line is
drawn now:

```
- Production runs recorded: 1
- Scenarios added to the corpus: 0
…
**1 recorded, 0 admitted to the corpus.** Recording is not harvesting: a run
becomes a scenario only if `aef loop harvest` re-executes it identically and its
behaviour survives redaction. Which of those it was is in that command's own
report line — run `aef loop harvest <graph> --runs <dir> --corpus <dir>` and read
it. Two answers are ordinary — every run passed (harvest promotes failures
unless `--include-successes`), or the daily limit held them back — and one is
not: `REJECTED, did not re-execute deterministically` on every run means the
ingestion path is broken, not quiet.
```

It names the reasons rather than one reason, because the digest reads a runs
directory and a corpus and does not run harvest; claiming to know which of them
applied would be a number nobody computed.

## Mutation checks

Each fix perturbed, the tests that should fail run, and the file restored from a
**sha256-verified byte backup** — never `git checkout --`.

```
$ python scratchpad/w/l2/mutate.py
M1 — drop `model_calls=` from the RecordedRun aef run writes (F-M6-1)
   FAILED as expected: 3 failed, 18 passed
   restored, sha256 verified e36a58ae8feb1ced…
M2 — drop the provider declaration from the RecordedRun (F-M6-2)
   FAILED as expected: 3 failed, 18 passed
   restored, sha256 verified e36a58ae8feb1ced…
M3 — replay with no declaration, as harvest did before (F-M6-2, other side)
   FAILED as expected: 1 failed, 30 passed
   restored, sha256 verified a44bad03295f2cc0…
M4 — remove the graph_id filter
   FAILED as expected: 1 failed, 30 passed
   restored, sha256 verified a44bad03295f2cc0…
M5 — remove the --runs/--module refusal (F-M6-3)
   FAILED as expected: 2 failed, 2 passed
   restored, sha256 verified bfed6adbe863eba5…

all mutations restored
```

**One near-miss, recorded because it is the reason the method has that rule.**
The script that removed M6's strict xfail marker sliced from the *first*
`@pytest.mark.xfail(\n    strict=True,` in the file, and there were two — so it
deleted three unrelated tests
(`test_obligation_six_scans_every_graph_under_a_widened_root`,
`test_the_live_provider_spec_can_rebuild_the_credential_free_provider`,
`test_the_sandbox_env_allowlist_carries_what_the_harness_login_needs`) along the
way. **The suite went green with them gone**, because a deleted test fails
nothing. It was caught by counting `^def test_` before and after per file, and
the three were restored byte-identically from `git show HEAD:<file>`; the final
diff of that file touches nothing but the M6 pins. A test count that only ever
goes up is not paperwork.

## The rubric

**No rubric dimension is moved here, and no row is added.** What changes is that
ADR 0164's pre-registered branch which actually fired is no longer the one
available. It pre-registered dimension 7 at 4 → 6 (+2) only if

> **(a)** real runs — objectives from the repo's own purpose, answered by the
> real harness — entered the corpus **through `harvest`**, with redaction on and
> the scan's counts quoted; **and** (b) the loop proposed a candidate from that
> evidence …

with the branch *"if `harvest` refuses every run, claim +0 and quote why"*. That
branch fired, and the "why" it quoted is F-M6-1 and F-M6-2 — both closed here.

**S7's +2 is therefore re-measurable, and M6's five real runs are the
artifact**: recorded, redacted, and sitting in `docs/research/pilot-marlin/`
with their scan. Re-measuring is a scorer's act, not a fix worker's —
`UPGRADE_LOOP.md` gives base moves to J0 — so this ADR says the evidence exists
and the obstruction is gone, and stops there. Two things it deliberately does
not claim: that clause (b) is met (a candidate proposed *from harvested*
evidence has not been run), and anything about the last +3, which stays
unclaimed because marlin is the same owner's repo and the tenant half of
dimension 7 needs someone else's traffic (ADR 0164, unchanged).

## Errata

- **ADR 0163 — F-M6-1, F-M6-2 and F-M6-3: all CLOSED here.** Its §6 sentence
  *"No run of any `aef migrate`-generated prompt-agent graph has ever been
  harvestable, on any repo, by any invocation"* was true when written and is
  false now; the end-to-end test asserting the opposite is
  `test_a_recorded_production_run_can_be_harvested_into_the_corpus`. Its "What
  still requires a person" item 3 (*"the two blockers are a fix worker's"*) is
  discharged. Items 1, 2 and 4 — a real checkout, a third party, and marlin's
  UUID-shaped secrets — stand untouched.
- **ADR 0119** said harvest *"redacts the input and re-executes, admitting only
  if behaviour is unchanged"*, and that was true of what the code did and
  misleading about what it could reach: **the redaction step was never reached
  on a model-calling run**, because the determinism re-check runs first and
  rejected every one of them. The pilot's redaction counts in ADR 0163 §5 could
  only be produced by running the policy directly, which is what that section
  did. The control is unchanged and is now on a path that gets to it.
- **ADR 0126** wired the cassette into the determinism re-check and into
  `record`/`bootstrap`, and **not into `aef run --record-runs`** — the one
  recording path the harvest pipeline is documented to be fed from. Its claim
  that "the cassette carries the model calls so re-execution needs no
  credential" was true of the cassette and vacuous for this path, because no
  cassette was written. It also pinned the clock and the model and left a third
  input — the provider's containment declaration — unpinned; that is F-M6-2 and
  it is closed here.
- **ADR 0182, open item 1** (the recording wrapper masks the provider name in
  the containment record) is **not** closed and now applies to one more path,
  `aef run --record-runs`. `RecordedRun.provider_name` is recorded so that
  closing it cannot silently reopen F-M6-2.

## Green bar

```
pytest -q                                2856 passed, 7 skipped, 4 xfailed
                                         (2867 collected, from 2850 before this
                                          branch — +17, none removed; and one
                                          strict xfail became a passing test,
                                          which is why passes are +18 and
                                          xfails are −1)
mypy aef examples                        Success: no issues found in 135 source files
ruff check .                             All checks passed!
ruff format --check aef tests examples   287 files already formatted
```

## Confidence

High on all three reproductions and on the fixes: each is a command whose real
output is pasted above, run before anything was edited and re-run after, and
each fix has a mutation that turns its test red and a byte-verified restore.

High, too, that this holds on real traffic and not only on a stub: the pilot's
five real `claude_code` runs, re-recorded through the fixed recorder from their
own recorded declarations and their own recorded answers, harvest 5 of 5, and
the same five as the old recorder wrote them still reject 5 of 5.

Lower, and named: **the pilot itself was not re-run.** Arm B replays the model's
words rather than asking for them, so the one input to the whole chain that is
not exercised end to end is the live `claude_code` subprocess — and the sentence
*"re-run the pilot today and it would harvest"* remains an inference, from a
mechanism that is now measured on that provider's real declaration rather than a
stub's. Re-running it costs live calls and is M-series work.

Also named: the three arms and the CLI end-to-end test use `command` +
`/bin/echo`, which is what lets CI run them with no credential and want none.
