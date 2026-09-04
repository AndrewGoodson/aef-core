# ADR 0131: The Codex path, measured

## Status
Accepted. Increment I15 of `TO_90_LOOP.md`; record in `IMPROVE_LOG.md`.
Rubric dimension 8: 4 → 5.

## Context

ADR 0040's claim is that the scaffold is not tied to one coding agent, and
ADR 0112's is that the model path is the harness's own login, so an
adopting repo needs no API key: `impl: claude_code` or `impl: codex`. The
first was reproduced end to end. The second never ran once. ADR 0112 said
so plainly — *"its parsing is a hypothesis until a run confirms it"* — and
the reason was not the adapter: the installed CLI was
`@openai/codex@0.135.0` (2026-05-29), and it rejected its own server's
model catalogue with `unknown variant 'max', expected one of none,
minimal, low, medium, high, xhigh`. The server had begun advertising a
reasoning level the build predated, so `codex exec` exited 1 before reading
a prompt.

A guess in a shipped adapter is the shape this repo keeps writing ADRs
about, and the rubric docked dimension 8 a point for exactly it.

## Decision

1. **Upgrade and measure.** `npm i -g @openai/codex@latest` → 0.153.2. Run
   the smoke, then the adapter itself.
2. **Keep the measurement runnable, not just recorded.**
   `tests/providers/test_codex_live.py` asserts every field the adapter
   derives — reply from `--output-last-message`, usage from the
   `turn.completed` event, model, stop reason — and is skipped unless the
   CLI is installed **and** `AEF_LIVE_HARNESS` is set. Opt-in twice because
   it spends the operator's quota and takes seconds; a network call inside a
   routine `pytest -q` is a flaky test waiting to happen.

   ```
   AEF_LIVE_HARNESS=1 pytest -q tests/providers/test_codex_live.py
   ```

## Evidence

```
before: codex-cli 0.135.0 → exit 1, "failed to load models cache: unknown variant `max`"
after:  codex-cli 0.153.2 → exit 0, last-message file "OK",
        turn.completed usage {input_tokens 19253, output_tokens 15}

CodexProvider.complete(), first live attempt, UNMODIFIED:
  argv    codex exec --ephemeral --skip-git-repo-check --sandbox read-only
          --json --output-last-message <file> --model gpt-5.5 <system\n\nuser>
  content 'OK'   model 'gpt-5.5'   stop_reason 'end_turn'
  usage   in=19975 out=26

mutations against the real CLI, each reverted:
  M1 usage scan reports zero            1 failed
  M2 reply not read from the file       1 failed
suite: 48 passed, 1 skipped (the live test skips without the opt-in)
```

Every line of the adapter's parsing, written blind from `codex exec
--help`, matched reality on the first run. That is a good outcome and also
a lucky one: it was a hypothesis for four days and nothing but this run
distinguished it from a wrong one.

## Consequences

- **Dimension 8: 4 → 5.** "Works with any coding agent" now rests on two
  measured backends rather than one measured and one assumed. Total 85 → 86.
- Two observations, neither acted on here. Codex's own context costs ~19–20k
  input tokens for a one-word reply, the same class of overhead ADR 0126 cut
  from ~211k to ~4.7k on the Claude path; nobody has looked for the Codex
  equivalent of `--safe-mode`. And `stderr` carries an MCP transport error
  (`HTTP 405`) on every run while the call still succeeds, so the adapter's
  non-zero-exit rule is doing the right thing for the right reason, but a
  future CLI that promotes that to a failure would break it.
- The failure mode was **version skew, not code**. An adopter whose CLI
  drifts behind its server sees `codex exec` fail before the adapter is
  reached. Worth a line in the adopter docs when someone hits it; not worth
  a version check the CLI will outgrow.

## Confidence

High on the adapter. Moderate on the path staying verified: it is one
model (`gpt-5.5`), one prompt shape, and a CLI that has moved 18 versions
in three months.
