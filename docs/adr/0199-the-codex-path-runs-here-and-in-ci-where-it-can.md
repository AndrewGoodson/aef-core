# ADR 0199: The Codex path runs here, and in CI wherever it can

## Status
Accepted. Increment N10 of `ABOVE_95_LOOP.md`; record in `IMPROVE_LOG.md`.
**Dimension 8 moves 4 → 5.**

## Context

J0b (ADR 0188) scored dimension 8 at 4/5 with one deduction, quoted verbatim:

> the Codex path is never exercised against the real CLI — its only live test
> is one of the three skips

Both halves of that are true and they are different problems. ADR 0131 *did*
run `CodexProvider` against the real binary and recorded the argv, the reply
and the usage — but from code alone the reviewer could not tell, because
`tests/providers/test_codex_live.py` is opt-in twice over (the CLI must exist
**and** `AEF_LIVE_HARNESS` must be set), so on every machine that has not
opted in it is a skip. And no CI job ever set the opt-in, so the path was
exercised **nowhere** on any push, on any runner, ever.

The opt-in is right and is not weakened here: it spends the operator's quota
and takes seconds, and a network call inside a routine `pytest -q` is a flaky
test waiting to happen. What was missing is a job that takes the opt-in
deliberately where a login exists.

## (a) The live test, run here

```
$ codex --version
codex-cli 0.153.2

$ AEF_LIVE_HARNESS=1 pytest -q tests/providers/test_codex_live.py
.                                                                        [100%]
1 passed in 4.87s
```

Green, unmodified, on 2026-09-05. ADR 0131's parsing — reply from
`--output-last-message`, usage from the `turn.completed` event, model, stop
reason — still matches the CLI five days and an unknown number of releases
later. That is the whole of what part (a) claims: the adapter answers.

## (b) The containment assertion, which is the part that mattered

ADR 0131's test asserts what the adapter *parses*. It says nothing about the
thing an adopter's containment story actually turns on, which ADR 0169 and
0179 spent a whole increment establishing: **`codex exec` has no system-prompt
flag**, so the persona is prepended to the USER turn, and ADR 0152's sentence —
*the file in Zone A IS the system message* — is FALSE on this backend.

`PromptAgentNode` records that in
`working_memory["<node>__containment"]`, and every previous assertion of it in
this repository was against a `_Declaring` fake whose `isolation` was a
hard-coded frozenset. A fake that declares `user_turn_persona` proves that the
node reacts to the declaration; it cannot prove the real provider makes it.

`test_a_prompt_agent_run_through_codex_records_the_persona_channel` closes
that: a real `Graph`, a real `GraphExecutor`, a real `CodexProvider` over the
real binary, and the containment record read off the final state.

```
$ AEF_LIVE_HARNESS=1 pytest -q tests/providers/test_codex_live.py
..                                                                       [100%]
2 passed in 9.24s
```

What it asserts, and each line is a claim that could have been wrong:

- the model answered (`working_memory["persona"] == "OK"`), so the containment
  record describes a run that happened;
- `isolation` contains `user_turn_persona` and `read_only_fs`;
- `isolation` contains **neither `no_tools` nor `single_turn`** — the two
  `claude_code` earns and this argv does not send. A containment record that
  claimed them would be ADR 0169's defect restored, and this is the assertion
  that would catch it;
- `persona_role == "user"`, and the warning is
  `prompt_agent.persona_in_user_turn` with "no system channel" in its message;
- `state.errors == []`, because this is a property of the provider the run was
  handed and never the run's error (ADR 0179, R3).

Two stale docstrings went with it: `CodexProvider`'s class docstring still
said "NOT reproduced … treat the output parsing as a hypothesis", and its
`isolation` property still said "this adapter has never been run (ADR 0112)".
Both were false from ADR 0131 onward and are now the reason a reader would
have believed the reviewer's finding.

## (c) The CI job

`ci.yml` gains one job, `live-harness`, whose contract is: **exercise the
harness backends wherever they CAN be, and say plainly why not otherwise.**

```yaml
runs-on: ${{ vars.AEF_LIVE_RUNNER || 'ubuntu-latest' }}
```

An owner with a logged-in machine points the repository variable at it; with
the variable unset the job still schedules on a hosted runner and skips
cleanly. It is never unschedulable and never mandatory.

**Detection is two questions, not one.** "Is the CLI on PATH" is cheap and
certain. "Is it logged in" is not knowable without spending a call, so the job
checks the two forms a credential actually takes — an API key handed in from
repository secrets, or the CLI's own auth file written by its login
(`~/.codex/auth.json`, `~/.claude/.credentials.json`). A guess at a third form
would be ADR 0150's shape: a check that passes on the wrong thing.

**The guard is on the target list, not on a boolean.** A runner with `codex`
and no `claude` runs the codex file and nothing else, rather than being
skipped wholesale because one of the two is missing.

Run under four runner shapes before it was written down:

| runner | detected | targets |
|---|---|---|
| this box | codex 0.153.2 + `~/.codex/auth.json`; claude present, no credential file | `tests/providers/test_codex_live.py` |
| hosted (no CLI) | neither installed | *(empty — the job explains and passes)* |
| CLI, no credential | codex present, logged out | *(empty)* |
| no CLI, secret set | neither installed | *(empty)* |

**The first row is an honest miss and is recorded as one.** On macOS the
Claude Code login lives in the Keychain, not in a file, so the detector reports
"CLI present, NO credential" and does not run the Claude live test on this
machine. The check is deliberately conservative: it never claims a login it
cannot see, so it under-runs rather than failing a build on a login it guessed
at. On a Linux runner — which is what this job is for — the credential is a
file and the row flips.

**A skip that prints nothing is indistinguishable from a pass**, which is the
exact failure J0b found in this repo's own nightly job (ADR 0188). The
complementary step prints which backend was missing, which half was missing,
and the two ways to fix it.

The job **never fails the build for a missing CLI or a missing credential**:
those are facts about the runner, not about the code. It does fail when a CLI
is present and its adapter is broken, which is the entire point.

## What is tested, and why it is the shell rather than the YAML

`tests/harness/test_ci_live_harness_job.py` extracts the detection block
**from the workflow** and runs it under those runner shapes, so the test and
the job cannot drift. A YAML-shape assertion would pass against a detector
that never emits a target — the same class of test ADR 0150 caught asserting
the shape of a flag whose value the CLI rejected.

Its own first draft had the defect it exists to prevent: two of the tests
called `shutil.which("codex")` and `pytest.skip`ped without it, so on every CI
runner they would have been skips — *"the only live test is one of the three
skips"*, reproduced inside the fix for it. They stub a `codex` on PATH now:
the detector asks `command -v codex`, so a file with the name and the execute
bit is the whole of what it is entitled to see, and nothing runs it.

## Mutations (3 on this increment, each reverted from a SHA-1-verified backup)

| # | mutation | caught by |
|---|---|---|
| M5 | the live step is not guarded on the detected targets | 1 workflow test |
| M6 | the live step drops `AEF_LIVE_HARNESS` (two skips reported as passes) | 1 workflow test |
| M7 | the detector selects a CLI with no credential | 1 workflow test |

M7 was **not caught** on the first attempt, and the reason is the finding
above: the tests that would have caught it were skipping for want of a real
`codex`. Fixed with the stub, then caught.

## Decision

- Rubric dimension 8: **4 → 5**. The falsification pre-registered for this
  increment was "the Codex live test RUNS here and green, and CI would run it
  where the CLI exists". Both hold, on artifacts.
- The live tests keep their double opt-in. The job takes the opt-in; nothing
  else does.

## Consequences

- `pytest -q` still makes no network call and needs no credential.
- An adopter reading `CodexProvider` is no longer told its parsing is a
  hypothesis, because it is not.
- The containment difference between the two shipped harness backends is now
  an executable assertion rather than a paragraph, on the one axis where
  getting it wrong hands an adopter a safety claim measured on a different
  provider.
- Still true and stated: this is one model (`gpt-5.5`), one prompt shape, and
  a CLI that moves fast. The job is what makes the next drift visible on a
  push rather than in six months.

## Confidence

High that the path runs here and that CI would run it where a CLI and a
credential exist — both were executed, the second under four runner shapes.
Moderate on the credential detection surviving: it understands two forms, and
a Keychain login is a third it deliberately does not claim to see.
