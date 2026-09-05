# AEF Agent Integration — canonical guide

This is the source-of-truth onboarding guide for **aef-core**. `aef adopt`
emits a repo-tailored copy of this into every adopted repo (see
`aef/cli/adopt.py::render_agent_integration_md` and docs/adr/0034); this
root copy is what that template mirrors, and what to read when working in
aef-core itself.

If you are a fresh coding agent — **Claude, Codex, Cursor, GitHub Copilot, or
any other** — read this top to bottom and you can install aef-core, run its
example, wire a node, and safely start the self-improving loop with no other
context. aef-core is harness-agnostic: the scaffold is plain Python plus the
`aef` CLI, so any agent that writes Python can use it.

## Which file your agent reads
`aef adopt` emits a native entry file for each major harness, all pointing
back to this guide — so the scaffold is never tied to one tool:

| Agent / harness | Entry file it reads |
|---|---|
| Claude / Claude Code | `CLAUDE.md` |
| OpenAI Codex (+ the cross-tool convention) | `AGENTS.md` (identical to `CLAUDE.md`) |
| GitHub Copilot | `.github/copilot-instructions.md` |
| Cursor | `.cursor/rules/aef.mdc` |
| any other | this file (`AGENT_INTEGRATION.md`) + `AUTONOMY.md` |

The self-improving-loop prompt below is written for Claude Code's `/loop`
command; on another harness, paste the same prompt body into that tool's
agent/chat and run it as an ordinary instruction — the phases and the
HARD-STOP gates are identical regardless of harness.

## What aef-core is
A repo-agnostic Agent Operating System scaffold: it is the thing dropped into
any repo so agents there inherit graph execution, memory, consolidated
knowledge, context retrieval under a token budget, evaluation, security,
observability, and durability without rebuilding any of it per agent.
**Only five things differ per agent:** Knowledge, Policies, Tools, Objectives,
Evaluation Metrics.

**It does not give you planning.** `Planner`/`PlanValidator` were deleted, not
deferred (ADR 0101), along with the knowledge-graph and token-optimizer
interfaces. An earlier version of the paragraph above listed planning as
something you inherit; it was never true. `docs/roadmap.md` is the
authoritative real-vs-stubbed answer — read it rather than this summary
whenever the two could disagree.

Two always-on invariants:
- **Two-plane determinism.** The kernel (control plane) is pure bookkeeping;
  every LLM/nondeterministic call lives inside a node declared
  `deterministic=False`. Never call a model from the kernel.
- **Vendor isolation (constraint #3).** `anthropic`/`openai`/`mem0`/`neo4j`
  imports live ONLY in `aef/providers/` and `aef/services/*/adapters/` —
  enforced by an AST scan in CI (`tests/test_vendor_isolation.py`).

## Start (working in aef-core)
```
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,anthropic,mem0]"
pytest -q                     # full suite
python -m examples.hello_agent.main   # a real end-to-end run (see examples/hello_agent/)
```
Green bar (must all pass before any change is "done"):
```
pytest -q
mypy --strict aef
ruff check .
ruff format --check aef tests
```

## Start (adopting aef-core into another repo)
Inside the target repo: `aef adopt --dir <path>`. It detects the current
framework — `langgraph` / `crewai` / `raw_sdk` / **`prompt_files`** / `none`,
where `prompt_files` means the repo's agents are `.md` prompts run by a coding
harness rather than Python call sites, reported with its counts
(`prompt_files (8 agents, 5 skills, AGENTS.md, .codex)` — that line is real
output, from a run on the marlin pilot clone) — and writes **17** files, never
destroying one: measured on that repo, 15 `wrote` lines and 2 `appended`. The
kit is the onboarding set
(`CLAUDE.md`, `AGENTS.md`, `AGENT_INTEGRATION.md`, `AUTONOMY.md`,
`FIRST_DAY.md`, `AEF_MIGRATION_CHECKLIST.md`), the config and shim
(`aef.yaml`, `aef_adapter.py`, `.gitignore`), the loop kit (`LOOP.md`,
`agents/README.md`, `corpus/README.md`, two `.github/workflows/`), and the
per-harness entry files (`.github/copilot-instructions.md`,
`.cursor/rules/aef.mdc`, `.claude/skills/new-model-check/SKILL.md`). It said
"six" here for months, and the drift was in the direction that matters: the
loop kit and `FIRST_DAY.md` were the files nobody was told they had.

**Never-DESTROY, and the five files that are appended to instead** (ADR
0153/0172). An existing file of a name adopt would write is skipped and
reported — except `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`,
`.cursor/rules/aef.mdc` and `.gitignore`, which gain a **signed** block:

```
<!-- aef:begin sha256=1a2b3c4d5e6f7081 -->
...
<!-- aef:end -->
```

and, in `.gitignore`, `# aef:begin sha256=…`. Sixteen hex characters — 64
bits, long enough that no prose carries one by accident.

**Only a signed pair is adopt's.** A bare `<!-- aef:begin -->` quoted in your
own prose is inert text: not searched, not matched, not touched, and the block
is appended after it. Re-running replaces adopt's own block and nothing else,
because the digest is a function of the body, so a second `aef adopt` changes
no byte of any file; deleting the block undoes it exactly. The digest is
**authorship, not integrity** — hand-edit inside the block and adopt still
replaces it, because the block is adopt's to maintain, and refusing there
would mean one stray keystroke stops the contract updating forever.

The never-destroy rule is **executable, not a claim in a document**:
`_verify_preserved` re-checks that the bytes before the block and the bytes
after it are still there, at the same ends, before every write; a violation
skips the file with a reason rather than writing it. Bytes are read and
written as bytes, and only the lines adopt is *adding* take the file's own
dominant line ending, so a CRLF or mixed file comes back with its author's
line endings intact.

The report says `appended` for those, beside `wrote` and `skipped`. The reason
is a measurement: on a real repo with eight `.claude/agents/*.md` agents,
adopt wrote a `CLAUDE.md` the repo does not use and skipped the `AGENTS.md` it
does — `grep -c AEF AGENTS.md` returned **0**, so the contract never reached
the file that repo's agents read. Two *signed* begins, a signed begin with no
end, non-text files, and symlinks are skipped with the reason, never guessed
at. A block written between ADR 0153 and 0172 carries a bare marker; it is
recognised and **migrated once**, with a printed notice, rather than left in
place beside a second copy of the contract.

Then `aef doctor` to confirm the setup, fill `aef.yaml`'s five surfaces, wire
a node in `aef_adapter.py`, and `aef run` / `aef eval` / `aef trace`.

**If your agents are prompt files**, there is no call site to convert:
`aef migrate` registers each `.claude/agents/**/*.md` (recursively) as its own
graph — four nodes, `retrieve -> prompt_agent -> reflect -> consolidate ->
END`, `graph_id` = the agent's name — and the `prompt_agent` node runs that
persona as one completion, reading the file at execution time so a proposer's
edit takes effect with no regeneration step.

### Which harness runs the call, and what containment you actually get

`model_provider.impl` in `aef.yaml`. **Containment is per-provider evidence,
not a stamped sentence** (ADR 0169) — this table is derived from the argv each
adapter builds for a fixed probe, so removing a flag retracts the claim in the
same commit:

| `impl` | persona channel | isolation claimed | how it was established |
|---|---|---|---|
| `claude_code` (default) | **system** | `no_tools`, `no_mcp`, `single_turn`, `no_project_context` | `--tools ""` (documented "disable all tools"), `--max-turns 1`, `--strict-mcp-config` + empty server set, `--safe-mode` — and only `--safe-mode` buys `no_project_context`. Reproduced end to end; the coding agent's own login is the credential, no API key |
| `codex` | **user turn** | `read_only_fs` | `--sandbox read-only`. No `--tools`, no `--max-turns`, no system flag. Not reproduced live on the authoring box |
| `grok` | **system** | `single_turn`, `no_web_search`, `no_subagents` | measured, not read off `--help`: **`--tools ""` suppresses nothing on 1.0.5** — the same argv read a planted file with one more turn allowed, so `no_tools` is NOT claimed. No `--safe-mode`; `--cwd <empty dir>` is the load-bearing lever and **~17.9k tokens of the operator's session still reach the model** (24,001 → 17,936 total input), so `no_project_context` is not claimed either |
| `command` | system if the template has a `{system}` slot, else **user turn** | **whatever you assert in `isolation:`** | your list, validated for spelling and recorded — never verified against your binary. The template's flags are deliberately not read as evidence: `--tools ""` means opposite things on the two CLIs above. Omit `isolation:` and the run claims nothing but the channel |
| `anthropic` | **system** | `no_tools`, `no_mcp`, `single_turn`, `no_project_context`, `no_local_execution` | structural: no `tools` parameter is sent, one request/one response, an API has no project discovery and spawns no process |

`cassette` reports the inner provider's set; a `fallback:` chain reports the
**intersection**, because the primary failing is exactly when the fallback
runs. Every run writes what it actually got to
`working_memory["prompt_agent__containment"]`, and appends a
`prompt_agent.persona_in_user_turn` error when the persona went in the user
turn. On the pilot run behind this section, an `impl: command` template with
no `isolation:` recorded exactly:

```json
"prompt_agent__containment": {"isolation": ["system_role"],
                              "persona_role": "system", "provider": "cassette"}
```

**GitHub Copilot's CLI is `impl: command`, configured by the owner who
installs it** — this repo ships no guess about its flags, because a flag's
shape is not a flag's value (ADR 0150), and it is the path every harness
released after this file was written takes.

The persona's own `tools:` frontmatter is parsed, **reported and never
obeyed**, under every impl. Honouring a markdown file's capability grant is
exactly what `PolicyEngine`'s deny-by-default exists to refuse.

The generated `FIRST_DAY.md` and `LOOP.md` carry the sequence and the sentence
that makes it honest: **a changed prompt cannot be scored from a cassette** —
every request is a miss — so a prompt candidate is gated live or not at all,
and the live noise floor (ADR 0156: mean 0.7639, spread 0.1666) is the bar.
**And "live" is an explicit per-repo opt-in, off by default.**
`gates.live_model_calls: true` in `aef.yaml` — read from the **base ref**, so
a candidate cannot grant itself the login — is what lets the gates' sandbox
worker inherit your harness credential, and therefore what lets a candidate's
code spend your quota. That worker is the one process here that executes code
an agent wrote, so the default is the containment property: no credential
inherited. Without the opt-in, `--cassette-miss live` is **refused by name**,
because the alternative is what ADR 0158 measured — `G2 fail — 2
previously-passing scenario(s) no longer pass`, which was a subprocess that
could not log in and not a judgement of the prompt. Every `gated` ledger event
records `live_model_calls`, so the audit trail says which passes spent it
(ADR 0181, closing ADR 0158's F-M5-2 and F-M5-3).

**`FIRST_DAY.md` is the adopter's sequence** — `aef migrate` through
`aef loop cycle`, in order, with the real output of every command and what
each step costs. Written from a terminal rather than from the source, because
three documents in this scaffold have told adopters things that were false
(aef-core ADR 0148).

**Two loop-CLI facts worth knowing before you read either.** One of
`--memory <file>` / `--no-memory` is **required** by `aef loop cycle` and
`aef loop run` — silence used to mean "do nothing" and this repo's own
scheduled cycle was a no-op every night while exiting 0 (ADR 0165/0167). And
the exit codes are four, not three:

| code | meaning | what to do |
|---|---|---|
| `0` | escalated to a human (the normal accept path; Tier-1 is off) | review it |
| `1` | the candidate was rejected | read the ledger's reason; retrying is fine |
| `2` | **halted**, or a usage error the command refuses to guess past | release the kill switch, or fix the invocation — do not retry |
| `3` | the command could not do its job — a crash, a bad config, an import error | fix it; fail CI on `>= 2` |

## The node contract (non-negotiable)
Every node has the fixed signature:
```
(AEFState, Context, Services) -> tuple[StateDelta, Route]
```
- Nodes take everything via `Services` (dependency injection) — no globals,
  no env reads, no self-constructed clients.
- Declare `deterministic: bool`. `True` means the replay engine WILL
  re-execute it and assert identical output — never on anything that calls a
  model, clock, or RNG.
- Declare `side_effects` (`pure`/`io`/`external_call`/`mutating`). Non-pure
  REQUIRES an `idempotency_key_fn` (enforced by the `Node` constructor).
  Resume is at-least-once; your key is what makes a re-executed side effect
  safe. The kernel does not dedupe for you.

## Running the self-improving loop (autonomously, safely)
Full spec: **`docs/autonomy/self-improving-loop.md`** (ADR 0033). One line:
audit by adversarial construction → reproduce failing → fix → verify (the
green bar) → ADR → commit → repeat until a **bounded** work-list is done,
then stop.

Run unattended, but pause and ask a human at the **HARD-STOP gates**: any
push to another repo or external publish; enabling `aef/evolution/`,
weakening the PolicyEngine, or removing a HITL gate; deleting/overwriting a
user file; a breaking public-contract change you're unsure of.

"Self-learning" = writing reflections into memory (rule-based critic/judge
first — `docs/design/phase3-reflection-critic-judge-brainstorm.md`). It does
**not** mean self-modification: `aef/evolution/` is gated by design
(ADR 0006/0010) and stays off.

## Guardrails you cannot route around
- Deny-by-default security (constraint #6): a tool with no declared scopes is
  denied; any positive-risk call routes to REQUIRE_HITL until approved.
- State is append-mostly `StateDelta`s; `plan` REPLACES on set (ADR 0019);
  scores/tokens/budgets are range-validated (ADR 0022/0025).
- Durability writes are atomic and resume recovers past a torn checkpoint
  (ADR 0031); HITL pauses are always resumable (ADR 0032).

## Where to look
- `aef/kernel/` — graph engine, Node/Edge, Services, checkpoint/replay
- `aef/state/` — the shared AEFState schema + migrations
- `aef/security/tool.py` — the policy engine every tool call passes through
- `aef/services/knowledge/` — consolidated knowledge (ADR 0110): repeated
  failure/success memory folded into entries a retriever can spend budget on.
  **Reachable from `aef.yaml` now**: `build_retriever` takes `knowledge=` and
  `aef run --config` builds it, so a `context:` block is enough — the "not
  reachable yet / `MERGE_READY_LOOP.md` A1" sentence that stood here was
  closed by ADR 0118 and outlived its defect. `aef migrate`'s generated graph
  wires `make_retrieve_node` and `make_consolidate_node` for you; a
  hand-written graph adds them itself.
  It is measured on retrieval coverage and **not** on task outcome: ADR 0175
  ran the layer fully engaged on a corpus whose failures recur and the task
  metric did not move, which disproves ADR 0110's coverage proxy for that
  corpus. Consolidation is kept because it is the mechanism the level above
  raw records needs; nobody should cite it as a score gain.
- `examples/hello_agent/` — a real, runnable end-to-end agent
- `docs/autonomy/self-improving-loop.md` — the full autonomy protocol
- `docs/autonomy/new-repo-bootstrap-loop.md` — copy-paste `/loop` prompt to bootstrap a new adopting repo
- `docs/adr/README.md` — every design decision, with rationale
