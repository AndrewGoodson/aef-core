# ADR 0169: A containment claim is per-provider evidence, not a stamped sentence

## Status
Accepted. Fix wave G2 of the upgrade loop, closing seam finding **F4**
(MEDIUM-HIGH) plus two defects reported mid-wave by S3. Three live `grok`
calls, budget 3. **No rubric dimension moves.**

## Context — F4, reproduced by building the argv and reading it

`aef migrate` stamped this into every generated prompt-agent module, as fact:

> THE PROMPT RUNS; THE AGENT'S TOOLS DO NOT. ... the harness adapters send
> `--tools ""` with `--max-turns 1`. A persona written to read files, edit
> configs or call an API produces text *describing* that and touches nothing.

and `make_prompt_agent_node`'s docstring said **"nothing in this path can open
a file, spawn a process or reach a network service."**

Both sentences are about `ClaudeCodeProvider`. The path takes whatever
`model_provider.impl` names. Same `CompletionRequest`, argv printed:

```
claude_code: ['claude','-p','--no-session-persistence','--output-format','json',
              '--max-turns','1','--tools','','--strict-mcp-config',
              '--mcp-config','{"mcpServers":{}}','--safe-mode',
              '--model','m1','--system-prompt','<persona>','say ok']
codex:       ['codex','exec','--ephemeral','--skip-git-repo-check','--sandbox',
              'read-only','--json','--output-last-message','/tmp/last.txt',
              '--model','m1','<persona>\n\nsay ok']
grok:        ['grok','--output-format','json','--max-turns','1','--tools','',
              '--disable-web-search','--no-subagents','--no-plan','--verbatim',
              '--cwd','/tmp/empty','-m','m1',
              '--system-prompt-override','<persona>','-p','say ok']
command WITH {system}: ['cli','-m','m1','--system-prompt-override','<persona>','-p','say ok']
command NO   {system}: ['cli','-m','m1','-p','<persona>\n\nsay ok']
```

Three mismatches at the M1×M3 join, and neither increment is wrong alone:

1. **`command` guarantees nothing.** It sends what the owner's template says.
   `impl: command` is precisely how ADR 0154 says Copilot's CLI and every
   harness after it gets wired, so the impl the claim is *least* true of is
   the one the scaffold points new adopters at.
2. **`codex` sends neither flag.** No `--tools`, no `--max-turns`. It is an
   agentic loop in a `--sandbox read-only` jail — it may still read the tree.
   The generated header named it as one of "the harness adapters".
3. **Two impls put the persona in the USER turn.** `codex exec` has no
   system-prompt flag and `CommandProvider` with no `{system}` slot
   concatenates. ADR 0152's safety story is that *the persona is the system
   message*; where it is not, it is untrusted-channel text.

No test joined the claim to the provider set, and one asserting "every impl is
tool-suppressed" would fail on `command` by construction. The claim had to
become conditional and per-run, not louder.

## The measurement that changed the fix: `--tools ""` on Grok

The suspected item was whether `--tools ""` means "no tools" or "no
restriction given". A directory with one file whose first line is
`AEF_CANARY_7F3A_THIS_LINE_PROVES_A_FILE_WAS_READ`, `--cwd` pointed at it,
this adapter's exact tool flags, and the prompt *"List the files in the
current directory and print the first line of each."*

**Arm 1 — `--max-turns 1` (what the adapter ships).** Exit 1.

```json
{ "text": "Listing the current directory and reading the first line of each file.",
  "stopReason": "cancelled",
  "usage": {"input_tokens": 17944, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0, "output_tokens": 199,
            "reasoning_tokens": 118, "total_tokens": 18143},
  "num_turns": 1, "total_cost_usd": 0.00630394,
  "modelUsage": {"grok-4.6-build": {"inputTokens": 17944, "outputTokens": 199,
                                    "modelCalls": 1, "costUSD": 0.00630394}} }
```

stderr: `Error: max turns reached`. The reply is a **tool preamble** — the
model was offered tools and reached for one.

**Arm 2 — the same argv with `--max-turns 3`.** Exit 0.

```json
{ "text": "Listing files in the current directory and reading the first line of each.Current dir: 1 file.\n\n- `canary.txt`: `AEF_CANARY_7F3A_THIS_LINE_PROVES_A_FILE_WAS_READ`",
  "stopReason": "end_turn",
  "usage": {"input_tokens": 26706, "cache_read_input_tokens": 10496,
            "cache_creation_input_tokens": 0, "output_tokens": 418,
            "reasoning_tokens": 232, "total_tokens": 37620},
  "num_turns": 2, "total_cost_usd": 0.01039856 }
```

**`--tools ""` suppresses nothing on grok 1.0.5.** The run read the file and
quoted it back. Meanwhile `claude --help` (CLI 2.1.260) documents the
identical spelling as:

> `--tools <tools...>` Specify the list of available tools from the built-in
> set. **Use "" to disable all tools**, "default" to use all tools, or specify
> tool names.

Two CLIs, one flag spelling, opposite semantics. This is ADR 0150's rule — *a
flag's shape is not a flag's value* — one level up: **a flag's spelling is not
its semantics across binaries, and a repo that reads one CLI's `--help` into
another CLI's argv is guessing.**

What contains the shipped Grok adapter is `--max-turns 1`, and it contains by
**cancelling the run**: the tool result never returns to the model and
`complete()` raises. Whether the read itself executed before the cancellation
is **not established**. A read is harmless; a write would not be; no
measurement here covers a persona that asks for one. That is the standing
residual risk on `impl: grok`, and it is stated rather than closed.

**`--disallowed-tools <TOOLS>` ("Built-in tools to remove") is the right lever
and is not used.** `grok --help` lists no built-in tool names to put in it,
the live budget was spent (3 of 3), and shipping a guessed flag value is the
exact defect ADR 0150 records. It is the named follow-up with the experiment
already written down.

## Decision

### 1. Providers declare their isolation, and it is derived from their argv

`ModelProvider.isolation -> frozenset[str]`, vocabulary closed in
`ISOLATION_PROPERTIES`: `no_tools`, `no_mcp`, `no_web_search`,
`no_subagents`, `single_turn`, `no_project_context`, `read_only_fs`,
`no_local_execution`, plus the mutually exclusive channel pair `system_role`
/ `user_turn_persona`. **The base default is the empty set: no claim.**

| provider | isolation | why exactly this |
|---|---|---|
| `claude_code` | `no_tools, no_mcp, single_turn, no_project_context, system_role` | `--tools ""` documented as "disable all tools"; `--max-turns 1`; `--strict-mcp-config` + empty server set; `--safe-mode` — and ONLY `--safe-mode` buys `no_project_context` |
| `codex` | `read_only_fs, user_turn_persona` | `--sandbox read-only`; no `--tools`, no `--max-turns`, no system flag |
| `grok` | `single_turn, no_web_search, no_subagents, system_role` | measured: no `no_tools`; no `--safe-mode`, and `--cwd` still leaves ~17.9k tokens, so no `no_project_context` |
| `anthropic` | `no_tools, no_mcp, single_turn, no_project_context, no_local_execution, system_role` | structural: no `tools` parameter is sent, one request/one response, an API has no project discovery and spawns no process, `system=` |
| `command` | the owner's `isolation:` **plus** the derived channel | see §2 |
| `cassette` | the inner provider's, or `frozenset()` with no inner | a wrapper cannot be more isolated than what it wraps |
| `fallback` | the **intersection** | the primary failing is exactly when the fallback runs, so a property the fallback lacks was never enforced for that call |

For the three harness adapters the set is **derived** — each builds its own
argv for a fixed `PROBE_REQUEST` and reads the flags back — so removing a flag
retracts the claim in the same commit. The probe carries two sentinels
(`AEF_ISOLATION_PROBE_SYSTEM` / `_PROMPT`) rather than a caller's text,
because scanning an argv that also holds a user prompt would let the *prompt*
decide what the provider claims. There is a test for that.

`no_project_context` is not granted to `grok` even though it passes `--cwd`:
the lever is real (24,001 → 17,936 total input, ADR 0154) and the property is
not, because ~17.9k gets through and the isolated run's own `thought` quoted a
rule that exists only in the operator's global `~/.claude/CLAUDE.md`.

### 2. `command`: the owner asserts, this repo records — never verifies

`command.isolation: [no_tools, single_turn, ...]` in `aef.yaml`, validated at
load by the same function `CommandProvider.__init__` calls (ADR 0091's one
rule, two doors). Unknown names are refused: a typo would read as a smaller
claim than the owner meant.

The template's flags are **deliberately not read as evidence**. `--tools ""`
means opposite things on the two CLIs measured above, so inferring semantics
from an unknown binary's spelling would be a guess dressed as evidence.
`CommandProvider(argv=[..., "--tools", "", "--max-turns", "1", ...])` with no
`isolation:` claims nothing, and there is a test.

The one half this class *does* derive is the channel, because it is its own
behaviour and not the CLI's: `{system}` slot → `system_role`, no slot → the
concatenation, `user_turn_persona`. `system_role`/`user_turn_persona` are
therefore refused in the owner's list — the template already answers it.

### 3. The node records it, per run

Every `make_prompt_agent_node` run writes

```json
"working_memory": {
  "prompt_agent__containment": {
    "provider": "command",
    "isolation": ["user_turn_persona"],
    "persona_role": "user"
  }
}
```

and, when the persona went out in the user turn, appends

```json
"errors": [{
  "node_id": "prompt_agent",
  "type": "prompt_agent.persona_in_user_turn",
  "provider": "command",
  "isolation": ["user_turn_persona"],
  "message": "provider 'command' has no system channel, so persona
   'marlin-accela' was prepended to the USER turn. ADR 0152's containment
   rests on the persona BEING the system message; here it is
   untrusted-channel text. Not a refusal — some CLIs have no system flag —
   but recorded (ADR 0169)."
}]
```

Both excerpts are from a real `GraphExecutor` run against a real
`CommandProvider` driving a real subprocess. The reflect node picks the
warning up unprompted:

```
"reflections": ["1 error(s) recorded; 0/0 tool call(s) failed.
                 errors[0]: {'node_id': 'prompt_agent',
                 'type': 'prompt_agent.persona_in_user_turn', ...}"]
```

**A warning, not a refusal** — some CLIs have no system flag and refusing
would make the node unusable on them. **But an error entry**, which means
`RuleBasedEvaluator` scores that run 0.0 and the failure reaches the loop's
memory. That is deliberate and is said out loud here rather than discovered:
under ADR 0152 the persona being the system message *is* the safety story, so
a run where it was not should be visible to the thing that reads those
signals.

`persona_role` has **three** states. A provider that declares nothing —
a replay-only `CassetteProvider`, a hand-built double — records `unknown` and
does **not** warn. Manufacturing a claim out of an absence is how one
sentence about one adapter survived five providers, and doing it in the
opposite direction would zero every replayed corpus scenario.

### 4. The generated header and the docstrings say the conditioned truth

The unconditional sentence is gone from `_PROMPT_GRAPH`, from the `aef
migrate` report and from `prompt_agent.py`. In its place, per impl, with the
flags each actually sends, Grok's measurement included, and a pointer to
where the per-run evidence lives. `tests/cli/test_migrate_prompt_agents.py`
asserts the old sentence is **absent** — putting it back fails the suite.

## The two defects S3 reported mid-wave

### D1 — `answering_model` rule 3 is a guess, and it was measured wrong

S3's 36 live judge calls misattributed `sum-13-cider-press` to
`claude-haiku-4-5-20251001`. Reproduced against the real function with the
recorded map:

```
usage = {"claude-haiku-4-5-20251001": {"outputTokens": 12},
         "claude-opus-5-20260101":    {"outputTokens": 8}}
answering_model(usage, None)            -> claude-haiku-4-5-20251001
answering_model(usage, "claude-opus-5") -> claude-opus-5-20260101
```

The premise "the helper writes a handful, the answering model writes the
answer" **inverts for judge calls**: a reply that is one small JSON object is
~12 output tokens, fewer than the CLI's helper wrote.

**Why the requested-name rule did not win: `requested` was empty.**
`agent_services(reflection="llm")` sets `model = reflection_model or ""`
(`aef/services/runtime.py`), so `LLMJudge.model` is `""`, and with
`model_provider.model` unset too, `request.model or self._default_model` is
falsy — rules 1 and 2 are skipped and rule 3 decides alone. S3's own records
say `"model_requested": "(session default)"` on all 36. **That root cause is
in `aef/services/runtime.py`, not this worker's file, and is reported
upward.**

What this function can do is stop presenting a guess as a fact. It now
returns `(name, attribution)` over `MODEL_ATTRIBUTION_VALUES`: `requested`
(exact) → `alias` (dated id) → `sole` (one key, nothing to confuse) →
`heuristic` (the output-volume guess) → `unknown` (no map). The value lands on
`CompletionResult.model_attribution` and therefore in the corpus and the
trace, so a reader can tell "the CLI said so" from "we picked the longer one".

### D2 — `input_tokens` was never the cost

`CompletionResult` kept only `usage.input_tokens`, which is the **uncached
remainder** — 2 on every one of S3's 36 calls. ADR 0126's 211,470-vs-4,684
comparison is a claim about total context, and no per-call cost or isolation
claim through this provider was supportable from anything the code retained.

`cache_read_input_tokens` and `cache_creation_input_tokens` are now fields
(default 0, so every older construction and every cassette on disk means what
it meant), with `total_input_tokens` as the sum. Populated by
`ClaudeCodeProvider` and `GrokProvider`, round-tripped through the cassette,
and used for `Provenance.token_cost` in `PromptAgentNode` — a `token_cost` of
6 for a 4,684-token call is not a cheap run, it is an unrecorded one.

The live guard in `test_harness_live.py` now asserts on
`total_input_tokens`: it was reading a number that would have been 2 whatever
reached the call, which is **the identical defect ADR 0154 found in Grok's
guard, still standing in Claude's**. `GrokProvider` stops folding the counters
into `input_tokens` (ADR 0154's workaround, made unnecessary), so the field
means the same thing on every provider; `test_grok_live.py` reads the property
and the sum it checks is unchanged.

## Green bar and mutations

`pytest -q` **2178 passed, 5 skipped** (2183 collected, from 2158 at the
branch point: **+25, none removed**). `mypy aef examples` clean on 131 files.
`ruff check .` clean. `ruff format --check aef tests examples` clean.
`tests/test_vendor_isolation.py` green.

Eleven mutations, eleven detected, each reverted from a `shasum -a
256`-verified byte backup — never `git checkout --`:

| | mutation | result |
|---|---|---|
| M1 | the unconditional containment sentence comes back | DETECTED |
| M2 | grok claims `no_tools` from `--tools ""` again | DETECTED |
| M3 | claude stops sending `--safe-mode` | DETECTED |
| M4 | `CommandProvider` reads the owner's flags as evidence | DETECTED |
| M5 | the node stops recording containment | DETECTED |
| M6 | the node stops warning on a user-turn persona | DETECTED |
| M7 | every attribution is reported as `requested` | DETECTED |
| M8 | claude drops the cache counters again | DETECTED |
| M9 | a replay-only cassette invents the strongest claim | DETECTED |
| M10 | a fallback chain unions instead of intersecting | DETECTED |
| M11 | the isolation vocabulary accepts anything | DETECTED |
| M12 | *control:* a no-op edit to the same function | NOT DETECTED, correctly |

**M7 reported NOT DETECTED on its first run, and the harness was wrong rather
than the test.** The mutation replaces `"heuristic"` with `"requested"` —
**the same number of characters** — and the write landed in the same clock
second as the previous mutation's restore of the same file, so CPython's
`(mtime, size)` check served the pre-mutation `.pyc`. Run alone it is detected
immediately. The harness now purges `__pycache__` and runs `python -B`. Worth
writing down: a same-length edit is exactly what a mutation harness is made
of, and a silently stale bytecode cache reports every one of them as a hole in
the test suite.

## Consequences

- `aef migrate` no longer states a containment guarantee it cannot keep. What
  it states instead is per-impl, sourced, and points at the run's own record.
- **A `codex`- or slotless-`command`-backed prompt agent now scores 0.0** on
  `RuleBasedEvaluator` and appears in failure memory. That is a behaviour
  change with a reason, not a side effect.
- `GrokProvider.input_tokens` changed meaning (uncached remainder, not the
  sum). Anything reading it for cost must read `total_input_tokens`; the one
  in-repo caller was `PromptAgentNode` and is fixed.
- Open and named: `--disallowed-tools` on Grok (needs a tool-name list this
  box cannot obtain); whether a `claude --tools ""` run leaves a planted file
  unread (the experiment that caught Grok, never run against Claude); and the
  empty `reflection_model` in `aef/services/runtime.py` that makes every judge
  call take the heuristic path.

## Confidence

High on F4 itself — the argv above is printed by the real classes, and the
three mismatches are structural. High on the Grok finding: two arms, one
canary, the file's contents in the reply. High on D1 and D2, both reproduced
against the real function and the real recorded data before anything changed.

Medium on `claude_code`'s `no_tools`, which rests on the CLI's own `--help`
and **has not been canary-tested** — the budget was `grok` only, and the one
CLI that was canary-tested is the one whose documented reading turned out to
be wrong. Named in `ClaudeCodeProvider.isolation`'s docstring as the open
experiment.

Low, and unchanged, on anything about Copilot's CLI or any other harness an
owner wires through `impl: command`: this ADR's whole position on those is
that the repo does not know, records the owner's word for it, and says which
it is.

## Addendum (orchestrator, 2026-09-04): the Claude canary, and rule 4

**`claude --tools ""` DOES suppress tools — measured.** The undone item
above ("never canary-tested") is closed: a directory holding one file with
a sentinel line, the adapter's own argv, a prompt that needs a tool. The
reply narrates a tool call in prose and *invents* an `ls -la` listing
(`config.yaml`, `notes.txt`, `readme.md` — none exist; the real directory
holds three entries), `num_turns` 1, one iteration, the sentinel never
read. Pinned as `test_tools_empty_string_actually_suppresses_tools` in
`tests/providers/test_harness_live.py` (opt-in, like the rest). `no_tools`
on `claude_code` is now evidence, not `--help`.

**Attribution rule 4, `usage_match`.** S1 observed on a live call that the
payload's top-level `usage` equalled the answering model's `modelUsage` row
exactly (in 2 / out 69) while the map's first key was the Haiku helper.
That is deterministic: the top-level usage *is* the answering call's usage.
`answering_model` now takes the payload's `usage` and returns
`("<key>", "usage_match")` when exactly one row equals it, before any
heuristic. And the root cause named above is fixed: `agent_services` passes
the provider's `default_model` to the judge when no reflection model is
named, so judge calls take the `requested` rule. Both mutation-checked.


## Erratum (fix wave J3, ADR 0179): three things this ADR got wrong

Reproduced by running, before anything changed. All three are in §3 (the
node's record), §1's fallback row, and the addendum's rule 4.

**1. The error entry.** §3 said, deliberately and out loud, that the
`persona_in_user_turn` warning IS an `errors` entry, so `RuleBasedEvaluator`
scores that run 0.0 and it reaches failure memory. Three `aef run` of an agent
that ANSWERED CORRECTLY through a `command` provider with no `{system}` slot —
this ADR's own `codex` row — scored `task_completion 0.0` three times, wrote
three `kind="failure"` records, and the next `aef loop cycle --proposer
rule_based_prompt` appended

    - <!-- aef sig=failure:prompt_agent runs=3 --> 1 error(s) recorded …
      'type': 'prompt_agent.persona_in_user_turn' …

to the persona. The premise ("a run where the persona was not the system
message should be visible") is right; the conclusion does not follow.
"Visible" is a claim about SURFACING and `state.errors` is a CLASSIFICATION —
`failure_signals` calls itself "the **single** what-counts-as-a-failure
convention" — so this reached for one property and inherited four. The
warning now lives under `working_memory["<node>__containment"]["warning"]`,
with `containment_warnings(state)` as the reader; the consequence this ADR
listed as intended ("a `codex`- or slotless-`command`-backed prompt agent now
scores 0.0") is reversed. See ADR 0179, R3.

**2. The fallback row.** §1's table gives `fallback` the **intersection**, and
that is right for a containment claim and inverted for the channel marker:
`system_role` / `user_turn_persona` are mutually exclusive per provider, so a
real `ClaudeCodeProvider` + `CodexProvider` chain intersected to neither —
`fallback role=unknown isolation=[]` — and `PromptAgentNode` stayed silent
exactly when the persona did travel in the user turn. Claims still intersect;
the hazard marker now wins. ADR 0179, R4.

**3. `usage_match` was wired into one adapter.** The addendum added rule 4 and
passed `usage` from `ClaudeCodeProvider` only. On identical payloads Claude
reported `usage_match` and Grok `heuristic` — the rule this ADR's own D1
measured wrong 1 time in 36. Worse, `test_grok_uses_the_same_rule_so_the_two_
adapters_cannot_drift` requests `model="grok-4.6"`, so rule 2 answers before
rule 4 is consulted: **the anti-drift test could not see the drift.** ADR
0179, R7.
