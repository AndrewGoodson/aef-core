# ADR 0213: The Claude login is a credential, and it is found by asking

Status: accepted 2026-09-23 (owner: "we should be using the Claude login").

## Reproduced

Two places decided "is there a credential?" by looking only for an API key
or a file, on a machine whose credential is a claude.ai login:

1. **CI's live-harness detector** (`ci.yml`, ADR 0199) selected
   `test_harness_live.py` only if `ANTHROPIC_API_KEY` was set or
   `~/.claude/.credentials.json` existed. On this Mac, `claude auth status`
   reports `"loggedIn": true, "authMethod": "claude.ai"`, the login is in the
   Keychain, and the file does not exist — so a self-hosted runner here would
   print `claude: CLI present, NO credential` and never run the Claude path,
   the path ADR 0112 made the default.
2. **`/new-model-check`** told its runner to look for `ant auth status` or the
   SDK's env vars. The 2026-09-03 run found neither, wrote "Credential: none
   on this box", and skipped its live step — on a box logged in to Claude
   Code.

## Decision

- CI asks the CLI: `claude auth status | grep '"loggedIn": true'` (no model
  call spent), and accepts `CLAUDE_CODE_OAUTH_TOKEN` from `claude
  setup-token` as the same login's headless form for a runner with no
  Keychain. The key and the file still count.
- The skill (repo copy and shipped copy) checks the harness login first and
  runs its live call through `claude -p`; the API key comes after.
- `test_harness_live.py` gains a live test of the shipped default
  (`claude-opus-5-5`) with `--effort`, under the login.

The `anthropic` SDK adapter still needs an API key or an `ant` profile. A
claude.ai login is not an API credential and this repo does not feed one to
the SDK; `impl: claude_code` is how the login reaches a model.

## Evidence

- The real detector on this machine, before: claude not selected; after:
  `targets= tests/providers/test_codex_live.py tests/providers/test_harness_live.py`.
- `AEF_LIVE_HARNESS=1 pytest -q tests/providers/test_harness_live.py` →
  `4 passed in 86.89s`, including the new Opus 5.5 test.
- Mutations: detector's login clause removed → 1 failed; skill's login
  check renamed → 1 failed.
