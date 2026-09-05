# ADR 0112: The harness is the model

## Status
Accepted. Ships `aef/providers/harness_provider.py`, `impl: claude_code`
as the template default, and the wiring of `model_provider.model`.

## Context

ADR 0111's first run audited the Anthropic SDK adapter against Fable 5.1
and found it could not talk to any current model. That was true and
beside the point. The owner's correction: this repo, and every repo it is
adopted into, holds **no API key**. The agents are Claude Code and Codex
sessions plus `.md` personas; the only credential is the harness login.

Under that premise the runtime's model layer had one adapter, and it was
the one no adopter could use. `CLAUDE.md` said as much, in the bullet about
prompt-file agents: "this runtime has nothing to attach to at the agent
layer." The reflection and consolidation nodes were rule-based not only by
design (ADR 0046, 0110) but by necessity — an LLM summariser existed and
nothing could run it.

A second, smaller defect surfaced while wiring: `model_provider.model` in
`aef.yaml` validated and was read by nothing. `build_model_provider`
constructed `AnthropicProvider()` with no arguments. This is the ADR 0100
shape — a block that validates while nothing reads it lets an owner believe
something is configured.

## Decision

1. **A node's model call is one headless run of the harness CLI.**
   `ClaudeCodeProvider` spawns `claude -p --no-session-persistence
   --output-format json --max-turns 1 --tools "" [--model M]
   [--system-prompt S] <prompt>`. `CodexProvider` spawns `codex exec
   --ephemeral --skip-git-repo-check --sandbox read-only --json
   --output-last-message <file> [--model M] <prompt>`. Both implement
   `ModelProvider` unchanged; `FallbackProvider` chains them like any other.
2. **Single-turn and tool-less, by construction.** A graph node calling a
   model wants a completion. An agent that can edit the working tree from
   inside a node is a second, ungoverned write path around `PolicyEngine`,
   which is the exact defect ADR 0105 closed for shadow nodes. Multi-message
   requests are rendered as one `User:/Assistant:` transcript, and the module
   says so, because hiding a single-turn CLI behind a chat-shaped API is the
   dishonest option.
3. **`--bare` is never passed.** It skips the keychain read and the CLI
   answers "Not logged in · Please run /login" — with exit 0 and
   `is_error: true`. The adapter treats `is_error` as `ModelProviderError`
   for the same reason: the CLI reports auth and API failures as successful
   runs.
4. **No vendor SDK.** The module imports `subprocess`, `json`, `tempfile`.
   The runner is injected; every test hands in a recorded `HarnessRun` and
   spawns nothing. Constraint #3 is untouched.
5. **`impl: claude_code` is the template default** in both example configs
   and both scaffold templates. `anthropic` remains for repos that do hold a
   key.
6. **`model_provider.model` is the provider's default model.** A request
   naming its own model still wins.

## Evidence

- **Reproduced.** From inside a running Claude Code session on 2026-09-03:
  `claude -p --no-session-persistence --output-format json --max-turns 1
  --tools "" --model claude-fable-5-1 --system-prompt "Answer with exactly
  one word." "Reply with the single word OK"` → `result: "OK"`,
  `stop_reason: "end_turn"`, `is_error: false`, `usage: {input_tokens: 2,
  output_tokens: 4}`, `modelUsage: {"claude-fable-5-1": …}`. The same
  command with `--bare` → exit 0, `is_error: true`, `result: "Not logged in
  · Please run /login"`. Both shapes are the fixtures in
  `tests/providers/test_harness_provider.py`, verbatim.
- **Not reproduced.** `codex exec …` on the same box exited 1 before
  reading a prompt: `failed to load models cache: unknown variant "max"`.
  The installed Codex predates its server's model catalog. `CodexProvider`
  is built from `codex exec --help` — `--output-last-message` is the
  documented contract for the reply, the JSONL is scanned only for a
  `usage` object — and its parsing is a hypothesis until a run confirms it.

## Erratum (2026-09-04, ADR 0131)

The Codex path is no longer a hypothesis. The CLI on this box was
`@openai/codex@0.135.0` (May 29) and could not parse its own server's model
catalogue — it rejected a `max` reasoning level its enum predated — so the
adapter could never be run. Upgraded to 0.153.2 and it answers: exit 0,
`OK` in the `--output-last-message` file, usage from the `turn.completed`
event. **`CodexProvider` worked unmodified on the first live attempt** —
argv, reply source and usage parsing all as written from `--help`. The
"not reproduced" and "parsing is a hypothesis" statements below were true
when written and are now superseded; see ADR 0131.

## Consequences

- The knowledge layer's LLM summariser (ADR 0110) is runnable in an
  agentic repo for the first time. It stays off by default; that decision
  was a coverage measurement and this ADR does not re-run it.
- Each node model call spends the harness login's quota and takes a CLI
  cold start (~seconds). Fine for reflection and consolidation, which run
  once per graph run; wrong for a node called in a tight loop. Timeout is
  600s and raises `ModelProviderError`.
- Nested invocation works: the reproduction ran from inside a session.
- `tests/config/test_schema.py` pinned the example config's impl to
  `anthropic`; updated deliberately, not incidentally.
- `CLAUDE.md`'s "nothing to attach to" bullet is rewritten to say what the
  attachment is and that the old sentence was true until now.

## What this does not decide

- Whether a node should ever be allowed tools through the harness. No — see
  decision 2 — but a future ADR could open a governed path if `PolicyEngine`
  can see the calls, which today it cannot.
- Anything about `aef/evolution/`. The provider is a model path; the
  disablement (constraint #7) is unchanged and the AST scan still holds.

## Erratum (2026-09-05, ADR 0181)

"The coding agent's own login IS the credential — no API key anywhere" was
true of every process this repo spawned **except the one that runs candidate
code**. The gates' sandbox worker (ADR 0094) inherits an environment scrubbed
to `sandbox.DEFAULT_ENV_ALLOWLIST`, which carries no `USER`, and `claude -p`
answers `Not logged in · Please run /login` without it — measured, and
narrowed to that one variable (`LOGNAME` does not substitute; `HOME` is not
needed). So from the day node bodies moved into a worker until ADR 0181, the
credential this ADR is about never reached the one place a candidate executes,
and `--cassette-miss live` failed every request from inside the gates.

Nothing above is wrong; it simply never said which processes it covered, and
the answer was "not the important one". It is now: the login reaches the gates'
worker when, and only when, the repo sets `gates.live_model_calls: true` in
`aef.yaml` — an explicit per-repo opt-in, off by default, read from the base
ref, and recorded on every `gated` ledger event. The default is still that a
candidate's code inherits no credential and cannot spend the operator's quota.

## Confidence

High on the Claude Code path and the wiring; the Codex path is documented,
tested against fixtures, and unconfirmed against the real CLI.
