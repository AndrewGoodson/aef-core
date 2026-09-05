# ADR 0126: Six seams, and a judge that could not read the answer

## Status
Accepted. Fix wave B of `ABOVE_90_LOOP.md` ("after each merge wave, launch
`seam-hunter`; every finding is reproduced or dropped"), branch
`fix/seams-b`. Record in `IMPROVE_LOG.md`. Errata appended to ADR 0115, 0116
and 0118 where this wave contradicts what they say.

## Context

Seven for seven: every adversarial round in this program has found a defect
in freshly written code believed correct. This round found six, in five
components that were each individually tested and green:

1. **The ACE tally was backwards on success entries and blind to chained
   failures** (`_tally`, ADR 0118).
2. **`ClaudeCodeProvider` inherited the operator's session** — 211,470 input
   tokens per judge call.
3. **The prompt-surface test filtered away three of its own planted faults**
   (ADR 0120).
4. **`opaque_secret` redacted plain English**, and the harvested scenario was
   admitted with a placeholder objective (ADR 0119).
5. **Tallies are recomputed over a read window that the provenance is not
   bounded by** (ADR 0116) — documented, no code change.
6. **`harvest` re-executed with a pinned clock and an unpinned model**, so
   any run whose graph calls a model was rejected as non-deterministic
   (ADR 0123's cassette was never wired here).

Plus one the I11 increment reported and left: **neither judge's evidence
contained the answer it was scoring** (ADR 0115/0123), which is why the
judge A/B on the summary corpus reads 3/18 and 9/18.

Five of the six are seams in the sense `docs/dev-pod.md` uses: two components
each correct on their own, joined by an assumption neither states. `_tally`
is correct about "was the lesson in context"; `default_signature` is correct
that `A>B` is not `B>A`; nothing owned the question of what those two mean
together. `harvest` correctly pins the clock, `CassetteProvider` correctly
pins the model, and no test ran a model-calling graph through harvest.

## Decision

**1. The tally counts failures, and counts them by node list, not by string.**
`_tally` takes the entry's `kind` and returns `(0, 0)` for anything that is
not a `failure`: a success entry was scored `harmful` once for every time the
success recurred, because a run that repeats a success necessarily re-produces
its signature. Reproduction is now "the entry's failing-node list appears, in
order, inside a failure signature the run produced" — a subsequence, not set
membership, so `default_signature`'s rule that `A>B` and `B>A` are different
failures survives. A custom `signature_fn` whose signatures this cannot parse
still matches itself by equality.

**2. The provider does not inherit the session.** `--strict-mcp-config`,
`--mcp-config {}` and `--safe-mode` join the argv. `--bare` stays absent —
it skips the keychain read, which is the credential. `--safe-mode` is the
only documented flag that drops CLAUDE.md discovery, skills, plugins and
hooks while stating that "auth, model selection, built-in tools, and
permissions work normally"; `--restricted` and `--setting-sources` reach
settings files only, not memory files. `max_tokens` is documented as dropped
rather than silently ignored: the CLI has no output-length flag.

**3. The prompt-surface filter blanks code spans and nothing else.** The old
filter dropped every line containing a backtick, "guide" or "remove", which
is a filter that removes exactly the lines a document about removing prompt
text contains. `test_the_detectors_detect` now pushes every planted fault
THROUGH the filter, in both its plain and its disguised form, and a second
test pins the exemption that survives (a pattern inside backticks is a
quotation) together with its limit (an instruction standing beside a quoted
command is still an instruction).

**4. `opaque_secret` requires a letter, a numeral, and no hyphen.**
Hyphenated key shapes are already covered by `api_key` and `bearer`, which
are prefix-anchored rather than shape-guessed. The catch-all was guessing
from length alone and caught English.

**5. The window/provenance mismatch is disclosed, not patched.** See the
paragraph appended to ADR 0116's Consequences. Carrying tallies forward
across consolidations would be the second source of truth ADR 0091 forbids;
a windowed recompute is what "stateless recompute" costs.

**6. Harvest re-executes under a cassette.** `RecordedRun.model_calls`
round-trips in the payload (legacy runs load with none), `_reexecution_services`
builds `CassetteProvider(None, scenario.model_calls, on_miss="fail")` — no
live provider, because a harvest that reaches the network to decide whether a
run is deterministic has already lost the property it is checking — and the
cassette travels into the promoted scenario so the gates can replay it too.

**7. The judges see the answer.** `_evidence` includes the string-valued
`working_memory` entries, first, as `working_memory[key]:`, excerpted at
`MAX_ANSWER_CHARS` (600) rather than the shared `MAX_EXCERPT_CHARS` (160).
The higher cap is justified and not free: on a content task the answer is
the thing being scored, not corroborating evidence, and 160 characters
truncates a 35-word summary at about two thirds and then asks the judge to
score completeness. It is still a cap, and every entry in the class is cut
at the same length, so bulk cannot read as quality within the class. At most
`MAX_WORKING_MEMORY_ITEMS` (4) entries are rendered, so a state carrying many
strings cannot crowd the errors that explain the answer out of the total item
cap, which is unchanged.

## Evidence

Every finding was reproduced by RUNNING before anything was changed. The
seam-hunter's scripts are in the session scratchpad; copies were run from
`.scratch/`.

```
F5  .scratch/repro_tally.py (parts 4a, 4b)
  before  success:<objective>  occ 4  helpful 0  harmful 2   <- four clean runs
          failure:fetch        occ 2  helpful 1  harmful 0   <- run failed fetch>parse
  after   success:<objective>  occ 4  helpful 0  harmful 0
          failure:fetch        occ 2  helpful 0  harmful 1

F6  .scratch/repro_provider.py + `claude --help` (CLI 2.1.260)
  argv before  claude -p --no-session-persistence --output-format json
               --max-turns 1 --tools "" --model m <prompt>
  argv after   ... --tools "" --strict-mcp-config --mcp-config {} --safe-mode ...
  seam-hunter's measurement, NOT re-measured (model quota exhausted):
    as issued 211,470 input tokens/call ($0.18 cached, $2.22 uncached)
    with --strict-mcp-config --mcp-config {}  4,684 (seam/claude_nomcp.json)
  max_tokens=400 in the request, "400" nowhere in the argv: confirmed, documented

F9  .scratch/repro_prompt_filter.py
  detector hits vs hits after the old filter, four planted lines:
    "Do not narrate your steps; the model guide says so."      hit -> HIDDEN
    "Never use bullets in the final report (see the style guide)." hit -> HIDDEN
    "CRITICAL: YOU MUST verify before you remove anything."    hit -> HIDDEN
    "Don't narrate. Hold all findings until the end."          hit -> hit
  after the fix all four are visible; no current surface file trips the
  stricter filter, so no prompt file needed editing

F10 .scratch/repro_redaction.py, and directly against the policy
  before  "migrate-the-customer-billing-pipeline-to-v2-with-zero-downtime"
          -> ("opaque_secret",) -> objective replaced by a placeholder
  after   -> () ; "v2-migrate-...-with-zero-downtime" -> () ;
          "test_a_downstream_node_counts_as_a_recurrence_of_its_own_lesson" -> ()
          44-char mixed token -> ("opaque_secret",) ; base64 payload -> ("opaque_secret",)

F8  .scratch/repro_tally.py (part 5), six failing runs with the lesson in context
  default window          occ 6  harmful 4
  candidates_per_kind=2   occ 6  harmful 2   (same store, unchanged records)

F12 tests/harness/test_harvest.py (new), a graph whose node calls the provider
  before  promoted ()  rejected_nondeterministic ("m1",)
  after   promoted ("m1",)  live provider called exactly once (the recording)
  found on the way: the output scan read `RecordedCall.key` — a SHA-256 the
  harness computes — as an `opaque_secret`, so every model-calling run was
  rejected "a secret survived redaction". All twenty ADR 0123 summary
  scenarios match it. The scan now drops the computed digest and nothing else;
  a secret planted in the model's REPLY is still rejected.

F13 tests/reasoning/test_llm_reflection.py (new), fake provider
  the judge prompt now contains `working_memory[summary]: <the answer>`;
  the LIVE judge A/B was NOT re-run (ADR 0123's 3/18 and 9/18 stand as the
  measurement of the defect, not of the fix)
```

Mutations — each perturbed the production value, ran, failed, was reverted,
and the file diffed clean afterwards:

```
M1  success entries tallied again                    1 test failed
M2  reproduction by string equality                  2 tests failed
M3  subsequence weakened to a set subset             1 test failed
M4  isolation flags removed from the argv            1 test failed
M5  --mcp-config points at the operator's config     1 test failed
M6  the old guide/remove line filter restored        1 test failed
M7  any line containing a backtick dropped whole     1 test failed
M8  the shape-only opaque_secret restored            1 test failed
M9  hyphens allowed back into the character class    1 test failed
M10 the letter+numeral requirement dropped           1 test failed
M11 harvest re-executes with an empty cassette       3 tests failed
M12 model_calls not loaded from the payload          4 tests failed
M13 the output scan reads the digest as tenant text  2 tests failed
M14 working_memory left out of the evidence          3 tests failed
M15 the answer excerpt uncapped                      1 test failed
M16 no inner cap on working_memory items             1 test failed
```

Green bar: `pytest -q` 1800 passed (from 1744, +56); `mypy aef examples`
127 files clean; `ruff check .` and `ruff format --check aef tests examples`
clean. One flake seen once and not reproduced in two further full runs:
`test_closing_the_session_leaves_no_container_running` compares the set of
containers running on the host, so anything else on the machine starting a
container while it runs fails it. Nothing in this wave touches that path.

## Erratum (2026-09-04, ADR 0150)

The `--mcp-config {}` this wave added is **rejected by the CLI** — its
schema requires `mcpServers` — so every `ClaudeCodeProvider` call exited 1
from the moment this ADR landed until ADR 0150 fixed it. The tests could
only assert argv's shape because the quota was exhausted that day, and
argv was well formed. ADR 0150 also separates the attribution this ADR
never did: `--safe-mode` alone reproduces the isolation (input_tokens 2),
so the 211,470 -> 4,684 reduction credited to the MCP flags belongs to
`--safe-mode`. The MCP flags are kept, correct and redundant.

## Consequences

- **No rubric dimension moves.** This wave fixes defects and documents two
  disclosures; it measures no new capability. Dimension 3's 8 was scored on
  an A/B whose result F13 now explains — re-scoring it needs the A/B re-run
  with the answer in evidence, which needs quota this session did not have.
- **The judge A/B must be re-run before anyone cites 3/18 or 9/18 again.**
  Those numbers measure judges that could not see the answer. They are still
  the correct measurement of the *defect*; they are not a measurement of
  either judge.
- **The per-call token cost of `impl: claude_code` is unmeasured after the
  fix.** 211,470 → 4,684 is the seam-hunter's number for the MCP flags alone,
  on the operator's box, before `--safe-mode` was added. Re-measure when the
  quota returns: one `aef loop score` run with `reflection.impl: llm` and the
  `usage` block from `--output-format json`.
- **`--safe-mode` is documented, not verified.** It is listed in
  `claude --help` for CLI 2.1.260 and was not exercised against a live call.
  The CLI tolerates unknown options silently (verified: an invented flag
  changes nothing about `--version` or an option-validation error), so the
  failure mode if a future CLI drops it is that the cost returns, not that a
  call breaks.
- **The recording side of F12 is not wired.** `aef run --record-runs`
  (`aef/cli/run.py`, owned by another worker this wave) still builds
  `RecordedRun` without `model_calls`, so a real harvested run from a
  model-calling graph will carry an empty cassette and be rejected —
  correctly, as before, but for a reason that is now fixable in one place.
  What `run.py` must do, and all it must do:
  ```python
  recording = CassetteProvider(model_provider, on_miss="live")
  services = agent_services(model_provider=recording, ...)   # as today
  ...
  RecordedRun(..., model_calls=recording.recorded)
  ```
  This is exactly what `recorder.record_run` already does (ADR 0123) and
  what `tests/harness/test_harvest.py::_record_model_run` does to build its
  fixture. The harvest side is complete and tested against it.
- **A weakened catch-all.** `opaque_secret` no longer matches a 40+ character
  string of letters only or numerals only. That is a deliberate trade: the
  false positive it removes (English, snake_case identifiers) was rejecting
  real scenarios and silently replacing objectives, and the prefix-anchored
  patterns plus the output scan remain. An owner with all-letter secrets
  extends the pattern list, which is the documented extension point.

## Confidence

High on F5, F9, F10, F12 and F13: each was reproduced, fixed, and mutation-
checked against a test that fails without the fix. Medium on F6 — the flags
are right by the CLI's own help and the token measurement is real, but the
argv after the fix has not been through a live call, and `--safe-mode`'s
effect is documented rather than observed. F8 is a disclosure with numbers
and no code, so there is nothing to be confident about except that the
numbers reproduce.


## Erratum (2026-09-05, ADR 0190)

**F12's cassette was wired into `record`/`bootstrap` and into the determinism
re-check, and NOT into `aef run --record-runs`** — the one recording path the
harvest pipeline is documented to be fed from (`--runs`, in `harvest`, in
`cycle`, and in the generated nightly workflow). `RecordedRun(...)` was built
there with no `model_calls=`, so the claim that "the cassette carries the model
calls so re-execution needs no credential" was true of the cassette and vacuous
for that path: there was no cassette to carry. Reproduced on five real runs of a
real repo (ADR 0163 §6) and offline at zero cost (ADR 0190), and fixed by
sending that path through the same recording wrapper.

A second, smaller correction to the same fix: it pinned the clock and the model
and left a third input to a prompt-agent run unpinned — the provider's own
`isolation` declaration, which ADR 0169 writes into `working_memory` on every
run and which the byte-for-byte trace comparison therefore reads. That is ADR
0163's F-M6-2, closed in ADR 0190 by recording the declaration and replaying it.
