# ADR 0152: A prompt-file agent is a graph

## Status
Accepted. Increment **M1** of `UPGRADE_LOOP.md`. Model: `claude-opus-5[1m]`
(the session default; the model authorisation is stated in `UPGRADE_LOOP.md`).
Four live model calls. **No rubric dimension moves** — adoption work claims no
rubric point (INGEST_LOOP's rule).

## Context — the reproduction, and it is a command that succeeded

The 2026-09-04 survey found **zero SDK call sites** in every eligible repo the
owner has. Their agents are `.claude/agents/*.md` persona files run by a coding
harness. `aef migrate` scans for functions whose bodies touch a vendor SDK, so
on a clone of `marlin` — 8 personas, 6 skills, `AGENTS.md`, `.codex/`, already
`aef adopt`ed — it printed:

```
$ aef migrate --dir .
scanned 38 Python file(s)
found 0 call site(s): 0 wrapped, 0 skipped


wrote .../agents/migrated/graph.py
  Zone A (agents/**) — agent-writable, the only tree the self-rewiring loop may propose changes to

This generated the PLUMBING, not the semantics. ...
```

Exit 0. The file it wrote has a `build_graph()` whose body is `raise
NotImplementedError`. Eight agents sat three directories away, unseen — and
that was the answer for **every** repo in the survey.

The premise of that behaviour stopped being true when `ClaudeCodeProvider`
landed (ADR 0112): a node's model call is one headless `claude -p` under the
harness's own login, so a persona body *is* a system prompt the runtime can
send. Nothing connected the two.

## Decision

### 1. `PromptAgentNode` — `aef/reasoning/prompt_agent.py`

`make_prompt_agent_node(agent_file=..., agent_name=..., route="reflect")`
builds a `Node` that reads one persona file, sends its body as the `system`
message and `state.objective` as the user turn through
`services.require_model_provider().complete(...)`, writes the reply to
`state.working_memory[<node id>]` and routes to `reflect`.
`deterministic=False`, `side_effects=SideEffect.EXTERNAL_CALL`,
`idempotency_key_fn` computed from **(agent name, objective)** — the objective
hashed, because a key is compared and logged, not read.

It lives in `aef/reasoning/`, not `aef/harness/`: it is a node, a node may only
touch `Services`, and `aef/reasoning/` already imports `aef.providers.base`
(the abstract interface, no vendor SDK — `tests/test_vendor_isolation.py`
still passes).

**The safety property, in the docstring because it is the whole point: the
prompt runs; the agent's tools do not.** The harness adapters send `--tools ""`
with `--max-turns 1`, so a persona written to read files, edit configs and call
the Accela API produces *text describing* that and touches nothing.
`CompletionRequest` has five fields and none is a tool list, so the persona's
own `tools: Read, Write, Bash` frontmatter cannot reach the provider even in
principle — it is parsed, **reported**, and never obeyed. Honouring a markdown
file's capability grant is exactly what `PolicyEngine`'s deny-by-default exists
to refuse. This is a real reduction in what a migrated agent can do, and it is
stated rather than discovered.

Frontmatter is read with a line-oriented reader, not a YAML parse: the body
below the fence is the payload and is passed through byte-for-byte, and every
other key in the wild (`tools`, `model`, `color`) is a capability hint this
node must not act on — not having them in a dict is the cheapest way to not act
on them. A file with no frontmatter is still an agent (name from the filename
stem); an unclosed fence is read as a body, because losing a prompt to a typo
in a delimiter is the worse failure.

**The persona is read at execution time, never copied into the generated
module.** That is what makes §3's Zone A widening worth anything: a proposer
that appends a lesson to the `.md` changes what the next run sends, with no
regeneration step in between. A missing file is a named refusal listing every
path tried — never an empty system prompt, because a node that quietly ran with
no persona would return a plausible answer from no agent at all and the run
would be scored as if the agent had been consulted.

### 2. `aef migrate` discovers `.claude/agents/**/*.md`

One graph per agent at `<agent-root>/migrated/<module>/graph.py`, `graph_id` =
the persona's `name`, wired `prompt_agent -> reflect -> consolidate -> END`.
The module component is the name sanitised to an identifier (`marlin-accela` →
`marlin_accela`), keywords and leading digits prefixed, collisions
disambiguated rather than silently overwritten.

One graph per agent, never several agents in one graph: F6's lesson (ADR 0149)
was three call sites in one generated graph leaving two nodes declared, routed
and **unreachable**, with nothing warning.

Discovery is **recursive**, and that was measured rather than assumed. A
scratch repo holding `.claude/agents/probe-one.md` and
`.claude/agents/sub/probe-two.md` was given `claude -p --agent
__definitely_not_an_agent__`, which is rejected *before any model call* and
names every agent the CLI found:

```
--agent '__definitely_not_an_agent__' not found. Available agents: ...,
probe-one, probe-two, ...
RC=1
```

Both. A flat glob would have migrated some of an adopter's agents and silently
left the organised ones behind.

The generated module is G0-clean by construction — it imports only `aef.kernel`
and `aef.reasoning`, so the allowlist that has no `pathlib`, no `hashlib` and no
`os` is satisfied — and passes `ruff check` + `ruff format --check` at the
adopting repo's own settings. The ruff test earned its place immediately: it
found seven `E501`s on the generated docstring's first line, where the repo name
plus the persona name pushed it past 100 columns.

### 3. Skills are NOT migrated, and are named rather than skipped

`.claude/skills/*/SKILL.md` is found, counted and listed in the report with the
reason:

- A `SKILL.md` body is *instructions injected into a session already in
  progress* when its description matches. It presumes that session's task,
  tools and files. A persona body is the whole of who the agent is.
- Skills routinely reference bundled material — `references/*.md`, scripts,
  templates — that a **tool-less single completion cannot open**, which is
  precisely the safety property above. A graph built from `SKILL.md` would send
  an instruction sheet stripped of the half it points at and return an answer
  that *looks* like an agent's.
- A skill has no objective of its own, and the objective is the user turn every
  generated graph sends.

Counting is one level (`<skills>/<name>/SKILL.md`), not `rglob`: `rglob` found
ten on the pilot where there are six, because two `SKILL.md` files live inside
one skill's own fixture corpus.

### 4. Zone A: design (a), `--agent-root`, opt-in per repo

**Chosen: (a) — one root, moved by configuration.** `aef migrate --agent-root
.claude/agents` writes the graphs to `.claude/agents/migrated/<module>/graph.py`,
and the repo passes the same `--agent-root` to every `aef loop` command. The
personas are then Zone A and the loop can propose a change to a *prompt*.

**Rejected: (b) — a multi-root `ZonePolicy` with one `is_zone_a()`.** The
criterion was *fewest changes to containment-boundary code*, and the count is
lopsided:

| | (a) chosen | (b) rejected |
|---|---|---|
| `aef/harness/zones.py` | 0 | `ZonePolicy.agent_root: str` → a tuple, plus `is_zone_a()` |
| `aef/harness/candidate.py` | 0 | via `enforce_zones` |
| `aef/harness/preflight.py` | 0 | `_zone_a_files`/`_zone_a_escapes`/`bless` all take a single `agent_root: str` and pass it to `git ls-tree` |
| `aef/harness/loop.py`, `workspace.py`, `trust.py`, `gates/base.py`, `suite.py`, `llm_proposer.py` | 0 | each reads `agent_root` or `classify_path` |
| `aef/cli/loop.py` `--agent-root` | 0 (already exists) | a list-valued flag |
| pinned test | none | `test_zones.py` asserts `set(ZonePolicy.__dataclass_fields__) == {"agent_root"}` |

(a) touches **no containment-boundary code at all**: `ZonePolicy(agent_root=...)`
already accepts an arbitrary root, `_segments` already handles a leading dot
segment, and Zone B still wins unconditionally — verified:
`inspect_path("aef/harness/gates/g0_static_safety.py",
ZonePolicy(agent_root=".claude/agents")).zone is Zone.B`.

(a)'s assumption — "Claude Code ignores a `.py` under `.claude/agents`" — was
**verified with the CLI, not assumed**, in the same zero-model-call probe as §2:
with `.claude/agents/migrated/probe_one/graph.py` on disk, the CLI's agent list
contained `probe-one` and `probe-two` and **nothing** from the `.py`. No agent
named `migrated`, `probe_one` or `graph`; no warning; no error.

**Opt-in, and the default tree is unchanged.** Widening Zone A is a scope
decision, not a default. `aef migrate` defaults to `agents`, and the report says
in words which of the two states the repo is in — computed from the classifier
the gates themselves use:

```
BLAST RADIUS — what the self-rewiring loop may now propose changes to.
  Zone A is 'agents'. The generated graphs are inside it.
  The PERSONA FILES are NOT (.claude/agents/accela-agent.md is Zone C).
  So the loop may improve the generated GRAPH and never the PROMPT: ...
  To widen it, re-run as
    aef migrate --dir . --agent-root .claude/agents
  and pass `--agent-root .claude/agents` to every `aef loop` command as well.
```

and, widened:

```
  The PERSONA FILES are inside it too (.claude/agents/accela-agent.md is Zone A).
  ... It also means a candidate may rewrite any file under '.claude/agents' —
  including every persona your harness loads. Pass the SAME --agent-root to
  every `aef loop` command ...
```

**One thing this increment does not do.** M1's brief asks for the opt-in to be
expressible in `aef.yaml`. `aef/config/` is held by another worker this wave, so
the opt-in surface today is the flag — `aef migrate --agent-root` plus the
`--agent-root` that `aef loop` has always had. Binding it to a config key is
left to the config owner and is named here rather than quietly dropped.

### 5. G0 on a `.md` in Zone A — run, and it was skipping silently

Run before anything was changed, on a repo with `--agent-root .claude/agents`
and a candidate whose only changed path is a persona:

```
changed paths: ('.claude/agents/persona.md',)
zone allowed: True
G0 outcome: pass
G0 reason: 1 file(s), 3 line(s), all Zone A, no static-safety violations
```

It did not crash — the first question. It **skipped silently** — the second:
`_scan` reads only paths ending `.py`, so "no static-safety violations" was a
claim about a file the gate had never opened. The behaviour is right; the report
was not, and for a prompt-file repo this is the *ordinary* case, because every
candidate M4 will propose has exactly this shape.

Now:

```
G0 reason: 1 file(s), 3 line(s), all Zone A; 0 Python file(s) statically scanned,
  no violations; 1 NOT statically scanned (not Python — an AST gate has nothing
  to say about them, and G1/G2/G5 judge them instead)
G0 evidence: ('.claude/agents/persona.md: not Python; no static scan',)
```

Nothing is loosened: a `.py` in the same candidate is scanned exactly as before
(`test_the_scan_still_rejects_a_forbidden_import_beside_a_markdown_file`), and a
pure-Python candidate gets no extra clause and no evidence line.

## Measurements — 4 live calls (budget ≤ 6)

**Quota preflight** (`TO_90_LOOP.md`, with ADR 0150's corrected
`--mcp-config '{"mcpServers":{}}'`): `is_error: false`, `result: "OK"`,
`usage.input_tokens: 2`, `cache_read_input_tokens: 2365`. Proceed. **1 call.**

**`aef migrate` on the pilot clone copy:** 8 prompt agents found, 8 graphs
written, 6 skills named and not migrated, 0 call sites (still true). Verbatim
extract:

```
found 8 prompt agent(s) under .claude/agents
  AGENT    marlin-accela  (.claude/agents/accela-agent.md)
            -> agents/migrated/marlin_accela/graph.py
            -> aef run agents.migrated.marlin_accela.graph --objective "..." --config aef.yaml
            graph_id='marlin-accela', wired prompt_agent -> reflect -> consolidate -> END
  ... 7 more ...
wrote 8 prompt agent graph(s)
```

**0 calls.**

**`aef run` on one migrated agent** (`--config aef.yaml`,
`model_provider.impl: claude_code`) returned real text grounded in the persona,
and the reflect/consolidate tail ran:

```
"working_memory": {
  "prompt_agent": "Two things must both be true: (1) Marlin-owned managed
   credentials ... and (2) a verified publication/modification-order watermark
   cursor is configured with a non-zero, source-justified `grace_days` ...
   Credentials alone are never sufficient — event dates like `openedDate` ...
   cannot serve as an ingestion watermark ..."
},
"reflections": ["no failure signals: 0 error(s) recorded, 0 tool call(s), none failed"],
"provenance": [{"node_id": "prompt_agent", "token_cost": 239, ...}]
```

**1 call.**

**`aef loop bootstrap` on two inputs:**

```
recorded 2 scenario(s) in the train split
  passed  accela-enable-preconditions
  passed  accela-watermark
0 of 2 recorded run(s) failed. ...
  recording spent 2 live model call(s). ...
  2 memory record(s) written to the durable store ...
```

Each scenario carries `graph_id: marlin-accela` and a one-entry cassette whose
request's system message is the persona body verbatim. **2 calls.**

The "0 of 2 failed" line is the honest state of this corpus: nothing here yet
drives the agent into a failing case, which is M4's input, not M1's claim.

## Green bar

`pytest -q`: 2039 passed, 3 skipped (2042 collected, from a baseline of 2002
collected on an exported `HEAD` — **+40, none removed**). `mypy aef examples`:
130 files, clean. `ruff check .`: clean. `ruff format --check aef tests
examples`: 246 formatted.

Five mutations, five kills, each restored byte-identical against a `shasum
-a 256` taken before the edit — never `git checkout --`:

| mutation | tests that failed |
|---|---|
| drop the `system` message from the request | 3 in `test_prompt_agent.py` |
| `rglob("*.md")` → `glob("*.md")` in discovery | `test_subdirectories_are_searched_because_the_cli_searches_them` |
| G0 stops naming unscanned files | 2 in `test_g0_non_python.py` |
| `_module_name` returns the name unsanitised | 2 in `test_migrate_prompt_agents.py` |
| idempotency key drops the agent name | `test_the_idempotency_key_is_the_agent_name_and_the_objective` |

One flake, pre-existing and untouched here:
`tests/harness/test_container_sandbox.py::test_a_timed_out_container_is_actually_dead`
failed once under full-suite load and passed alone (25 passed) and in an
earlier full run of the same tree — a container-timeout race.

## Consequences

- A prompt-file repo now has something to attach to at the agent layer. The
  sentence in `CLAUDE.md` that says otherwise is **not** retired here — M5
  replaces it when the acceptance test passes.
- A migrated persona is strictly less capable than the harness session it was
  written for. That is a containment property, not a limitation to be worked
  around, and it is written into the node, the generated module and the report.
- Widening Zone A hands the loop write access to every persona in the
  directory. Opt-in, named in the report, default unchanged.

## Defect found outside this increment's files (reported, not fixed)

`aef/providers/harness_provider.py::ClaudeCodeProvider.complete` sets
`answered_by = next(iter(model_usage), None)` — the *first key* of the CLI's
`modelUsage` map. On this run, with `--model claude-opus-5` passed, that key was
`claude-haiku-4-5-20251001` (the CLI bills a small helper model alongside the
requested one; the preflight JSON shows both keys), so the run's provenance and
the corpus record the wrong model:

```
"provenance": [{"node_id": "prompt_agent", "model": "claude-haiku-4-5-20251001", ...}]
```

`modelUsage` is a map, and "first key" is not "the model that answered". M3
holds `aef/providers/`.

## Confidence

High on the mechanism: every part was reproduced by running a command, and the
two CLI facts the design rests on (recursive agent discovery; a `.py` under
`.claude/agents` being inert) were measured from the binary rather than assumed.
Lower on breadth: one pilot repo, eight personas, one harness. Nothing here says
a *changed* prompt survives the gates — that is M4/M5, and the corpus this
increment recorded has no failing input for them to work from yet.


## Erratum (2026-09-04, ADR 0169, fix wave G2)

**"The safety property, in the docstring because it is the whole point: the
prompt runs; the agent's tools do not" is a claim about `ClaudeCodeProvider`,
and it was written — here, in `make_prompt_agent_node`'s docstring, and
stamped into every generated module — as a claim about the PATH.** The
sentence "The harness adapters send `--tools ""` with `--max-turns 1`" is
false of two of the five impls that path accepts and unverifiable on a third:

- `codex exec` sends **neither** flag. It is an agentic loop in a `--sandbox
  read-only` jail, and it has no system-prompt flag, so the persona goes in
  the USER turn.
- `grok --tools ""` was **measured** on 1.0.5 to suppress nothing: given one
  more turn the same argv listed a planted directory and quoted the file's
  first line back. `claude --help` documents the identical spelling as "Use
  \"\" to disable all tools". Same spelling, opposite semantics.
- `impl: command` — ADR 0154's answer for every harness after Grok, including
  Copilot's CLI — sends whatever an owner's argv template says and nothing
  else, and with no `{system}` slot prepends the persona to the user turn.

`ProviderMessage`-level statements in this ADR stand: `CompletionRequest` has
no tool field, and the frontmatter's `tools:` key is still parsed, reported
and never obeyed under every impl. What does not stand is the unconditional
"nothing in this path can open a file, spawn a process or reach a network
service."

Providers now declare an `isolation` set derived from the argv they build, the
node records it and the persona's channel per run
(`working_memory["<node id>__containment"]`, plus a
`prompt_agent.persona_in_user_turn` error entry), and the generated header
states the per-impl truth. ADR 0169 has the argv, the canary experiment and
the raw JSON.

\n

---

## Erratum, added by ADR 0168 (fix wave G1b)

**The command this ADR's report prints for a widened root cannot be run.**

§4 chose `--agent-root .claude/agents` as the opt-in, §2 has the report print
`aef run <dotted> --objective "..."` per agent, and `dotted` is the output path
with `/` replaced by `.`. Under the widened root that is
`.claude.agents.migrated.marlin_accela.graph`, and:

```
$ aef run .claude.agents.migrated.marlin_accela.graph --objective "x" --config aef.yaml
error: the 'package' argument is required to perform a relative import for
'.claude.agents.migrated.marlin_accela.graph'
```

A leading dot is a relative import to `importlib`, and **no** dotted spelling of
that path exists — `.claude` is not an identifier.

This ADR's Measurements section ran `aef run` on a graph written at the
**default** root, and ran `--agent-root` without ever running the command that
flag makes migrate print. Each half was exercised; the join was not. It is the
same seam shape as ADR 0168's F3 and it was in this increment's own evidence.

Fixed in ADR 0168: `aef run` (and `aef loop record`, which shares the loader)
accept a file path as well as a dotted name, and `migrate` prints whichever form
is runnable for the root the adopter chose. Refusing the root was rejected —
`.claude/agents` is this ADR's whole opt-in.


## Erratum (fix wave J3, ADR 0179): the generated template had no retrieve node

This ADR's template is `prompt_agent → reflect → consolidate → END`, and the
tail is defended at length as what makes an adopted repo learn. It is — and
nothing in it made an adopted repo USE what it learned. With no retrieve node,
`state.retrieved_context` is `[]` on every run an adopter ever makes, so
`retrieved_signatures` is `[]` on every reflection record and ADR 0118's
helpful/harmful tally is a constant. Reproduced: three real runs through the
real generated graph, one knowledge entry formed at `helpful=0 harmful=0`,
seen by nothing.

The template is now `retrieve → prompt_agent → reflect → consolidate → END`
with `entry_node="retrieve"`, and `PromptAgentNode` renders the retrieved
lessons into the USER turn after the objective. **This ADR's safety story is
unchanged and is the reason for that placement**: the persona is the system
message and is never modified at runtime, so a lesson — which is derived from
model output — travels in the turn data travels in rather than being spliced
into the operator's channel. The request is byte-identical when nothing was
retrieved. ADR 0179, R6.
