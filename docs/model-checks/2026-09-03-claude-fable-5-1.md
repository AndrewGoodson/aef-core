# Model check — `claude-fable-5-1` — 2026-09-03

First run of `/new-model-check` (ADR 0111). This run *is* the requested
Fable 5.1 review of the self-learning loop.

**Target:** `claude-fable-5-1`.
**Source of facts:** bundled `claude-api` skill, Claude Code 2.1.258
(`shared/model-migration.md` §"Migrating to Claude Fable 5.1" and §"…from
Claude Fable 5"; `shared/prompt-audit.md` signal tables; model table cached
2026-06-24).
**Credential:** none on this box (`ant` absent, `ANTHROPIC_API_KEY` unset).
**Branch:** `model-check/fable-5-1`, merged to `main`.

## Reproduced (ran on this box)

| # | Finding | Proof |
|---|---|---|
| R1 | `.claude/` wholly gitignored; `reproduce-first` and `seam-hunter` untracked — `CLAUDE.md` names files a clone does not have | `git ls-files .claude` → empty; `git check-ignore -v .claude/skills/reproduce-first/SKILL.md` → `.gitignore:15:.claude/` |
| R2 | Inventory grep detects planted faults | `.model-check-scratch/planted.py` (retired ID + `temperature`) and `planted.md` (`CRITICAL: YOU MUST … narrate … bullet`) both surfaced; scratch removed, tree clean |
| R3 | Each fix's test fails before the fix and detects its mutation | 9 new tests failed pre-fix; mutations M1–M4 (re-add `temperature`; disable tool-role refusal; disable refusal check; `max_tokens` back to 1024) each → `1 failed`; model-ID mutation (`claude-sonnet` restored) → `1 failed`; AUTONOMY block mutation → `1 failed`; skill-copy drift (one byte) → `1 failed` |

## Suspected (documented in the loaded guide, not run — no credential)

| # | Finding | Guide line |
|---|---|---|
| S1 | `AnthropicProvider` sent `temperature` on every call → 400 on Fable 5/5.1, Opus 5/4.8/4.7, Sonnet 5 | SKILL.md "Thinking & Effort" table: *Sampling (`temperature`/`top_p`/`top_k`) — Removed - 400*; migration.md §"Sampling parameters" |
| S2 | `ProviderMessage.role` admits `"tool"`, forwarded verbatim; the Messages API carries tool results as `tool_result` blocks in a `user` message | `python/claude-api/tool-use.md:219` `messages.append({"role": "user", "content": tool_results})` |
| S3 | `stop_reason == "refusal"` returned as `content == ""` with no error | 5.1 checklist `[TUNE]` "Add `stop_reason == "refusal"` handling before reading `response.content`" |
| S4 | `CompletionRequest.max_tokens = 1024` can be spent entirely on thinking | SKILL.md pitfalls "Don't lowball `max_tokens` … non-streaming default ~16000"; 5.1 "At `high` and above set a large `max_tokens` - it is a hard limit on total output (thinking plus response)" |
| S5 | `model: claude-sonnet` in `agent.example.yaml`, `agent.azure_sec.yaml`, `adopt.py`, `init.py` — not an ID, would 404 | SKILL.md "Use only the exact model ID strings from the table" |

## Prompt-surface scan (remove-first)

Ran `prompt-audit.md`'s greppable signals over `CLAUDE.md`, `AGENTS.md`,
`AGENT_INTEGRATION.md`, five `*LOOP*.md`, `HANDOFF_AND_NEXT_LOOP.md`,
`.claude/agents/seam-hunter.md`, `.claude/skills/reproduce-first/SKILL.md`,
`docs/autonomy/self-improving-loop.md`, `aef/cli/adopt.py`,
`aef/cli/adopt_loop.py`:

- anti-narration / anti-formatting / dated idioms / retired model names: **0 hits**
- caps escalation (`MUST|NEVER|ALWAYS|CRITICAL|IMPORTANT`): **5 hits**, all
  verification or safety rules (`the test MUST fail` in a mutation check,
  `NEVER git add -A`, `NEVER: enable Tier-1 auto-merge`) — keep list.

Nothing removed.

## What changed, per commit

| Commit | Change |
|---|---|
| `48ee1ef` | design spec |
| `71d8b71` | `/new-model-check` skill as package data; `adopt` ships it never-overwrite; repo copy pinned identical; `.gitignore` narrowed so `.claude/skills` and `.claude/agents` are tracked (R1) |
| `1c2a52f` | provider: no sampling params forwarded (S1); `role="tool"` refused by name pre-network (S2); refusal raises `ModelProviderError`, `FallbackProvider` falls through (S3); `max_tokens` default 16000 (S4) |
| `ea33774` | `claude-opus-5` in both example configs and both scaffold templates; `tests/test_model_ids.py` pins ID *shape*, not a model table (S5) |
| `1fd662a` | loop contract §9 + shipped `AUTONOMY.md`: the guide's autonomy, scope, test-coverage and targeted-edit blocks, verbatim; nothing removed; verification rules kept |
| (this) | ADR 0111, this report, `CLAUDE.md` pointer, skill wording |

## Deliberately left

- **Live spot-check** — not run: no credential. Re-run Step 3.4 on a box with one.
- **`LLMSummariser.temperature`** — now inert for Anthropic; a vendor-neutral field, its removal is a summariser decision.
- **Effort / sub-agent effort** — no agent definition declares either; the guide is explicit only where they do. Claude Code's effort is the operator's setting, not the repo's.
- **`display: "updates"`, per-message effort, server-side `fallbacks`, the batching nudge** — API-loop features; this repo's loop is the coding-agent harness, which injects the batching nudge itself. `FallbackProvider` is the repo's fallback.
- **A/B with prior-model scaffolding removed** — recommended by the guide; no prompt eval exists here to run it against. Follow-up.
- **`MERGE_READY_LOOP.md` Track A (A1 `knowledge=` wiring, A2, A4)** — untouched; out of this check's scope and still open.

## Green bar

`pytest -q` → **1571 passed** (from 1558; +13, none removed) ·
`mypy aef examples` → 118 files clean · `ruff check .` clean ·
`ruff format --check aef tests examples` → 210 files.

## Addendum — the credential is the harness (ADR 0112)

The owner corrected the premise mid-run: this repo and the repos it adopts
into hold **no API key by design** — their agents are Claude Code / Codex
sessions. S1–S4 above are real but were findings against a path no adopter
can use. The fix that matters is `aef/providers/harness_provider.py`:
`impl: claude_code` runs a node's model call as `claude -p --tools ""
--max-turns 1 --output-format json` under the session login.

**Reproduced:** `claude -p … --model claude-fable-5-1 "Reply with the single
word OK"` from inside this session → `result: "OK"`, `stop_reason: end_turn`,
`usage {input 2, output 4}`, `modelUsage` keyed `claude-fable-5-1`. Under
`--bare` the same call returns exit 0 with `is_error: true, result: "Not
logged in · Please run /login"` — which is why the adapter never passes
`--bare` and treats `is_error` as a provider error.

**Suspected — not reproduced:** `impl: codex`. `codex exec --ephemeral
--skip-git-repo-check -s read-only --json -o <file>` exited 1 on this box
before reading the prompt: `failed to load models cache: unknown variant
"max"` — the installed Codex CLI predates its server's catalog. The adapter
is built from `codex exec --help`; its output parsing is a hypothesis.
