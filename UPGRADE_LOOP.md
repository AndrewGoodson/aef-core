# Upgrade loop — old agentic repos get a real upgrade, and the score goes past 95

Two goals, one night, stated so each can fail on its own:

- **M — the upgrade.** Copying this repo into an *existing* agentic repo —
  one whose agents are `.claude/agents/*.md`, skills, `AGENTS.md`, a
  `.codex/` — gives it a self-learning loop over *those* agents, gated,
  under Claude, Codex or Grok. Proven on a clone of a real one.
- **S — the score.** Above 95 on `docs/research/self-learning-rubric.md`,
  or an honest statement of the number the measurements support.

Every rule of `IMPROVE_LOOP.md`, the multi-agent protocol of
`ABOVE_90_LOOP.md`, and the rules `INGEST_LOOP.md` added apply unchanged.
HARD-STOP gates bind: never enable `aef/evolution/`, never weaken
`PolicyEngine`, never Tier-1 auto-merge, never push anywhere but this
repo's `main`. Read `CLAUDE.md` and `.claude/skills/reproduce-first/SKILL.md`
first. **Adoption work claims no rubric point** (INGEST_LOOP's rule); the
S-thread claims points only on measurements.

## What was measured before this file was written (2026-09-04)

Read-only survey of the owner's repos (`/Users/raptor/*`, git repos with an
agentic surface), then `aef adopt` on a **clone** of one:

| repo | `.claude/agents` | skills | CLAUDE.md | AGENTS.md | `.codex` | py files | **SDK call sites** |
|---|---|---|---|---|---|---|---|
| datamining | 13 | 6 | Y | Y | – | 362 | **0** |
| marlin | 8 | 5 | – | Y | Y | 39 | **0** |
| keystone | 7 | 4 | – | Y | Y | 67 | **0** |
| dataco | 5 | 3 | Y | – | – | 2000+ | **0** |
| databento_ingestion | 3 | 3 | Y | – | – | 82 | **0** |
| Promethesus | 0 | 18 | Y | Y | – | 43 | **0** |
| Raptor (trading — **off limits**) | 26 | 18 | Y | Y | Y | 2000+ | 7 |

**Every eligible repo has zero SDK call sites.** Their agents are prompt
files run *by the harness*. `aef migrate` finds nothing in any of them;
`CLAUDE.md` already says so ("there is no call site to convert and this
runtime has nothing to attach to at the agent layer"). That sentence is the
gap this loop closes, and it is retired only when the acceptance test in M5
passes.

`aef adopt` on a clone of `marlin` (8 agents, 5 skills, AGENTS.md, .codex):
`detected framework: none`; wrote `CLAUDE.md` (which marlin does not use)
and **skipped `AGENTS.md`** (which it does): `grep -c AEF AGENTS.md → 0`.
The contract never reached the file the repo's agents read.

Harness interfaces, from `--help` on this machine: `claude -p --agent
<name> | --agents <json> | --system-prompt-file`; `grok --agent <NAME> |
--agents <JSON> | --output-format json | --json-schema | -m <model>`
(installed: `grok 1.0.5`, interface near-identical to Claude's); `codex
exec` takes instructions on stdin, `-c key=value`. **Copilot's CLI is not
installed** — owner action, not this loop's.

`ClaudeCodeProvider` works again as of ADR 0150 (`--safe-mode` measured as
the load-bearing isolation flag; `input_tokens 2`). Quota is available on
the session's default model.

## The model authorization, stated once

I3/I10/I11 were measured on `claude-fable-5-1`, whose quota is exhausted.
The owner said "Continue in opus" and "work through the night using your
best judgement". **Every S-thread measurement runs on the session default
(Opus) and re-measures its baseline arm on the same model** — a comparison
across models is not a comparison (TO_90's rule). Each ADR names the model.

## The honest ceiling, stated before starting — SUPERSEDED by ADR 0151

**J0 ran first and scored 68.5; the lower score stands on every dimension
(ADR 0151). The rubric heading is 68.** The paragraph below was computed
from 86 and is kept only as the record of what this loop expected before
the control it asked for was applied. The report recomputes the ceiling
from 68, with J0's seven named gaps — the no-op scheduled cycle, the
retrieval→prompt link, prose-only measurements, no CLI for the archive, no
persistence across runs, no live signal, the unexercised Codex path — as
the increments that can re-earn points, each on an artifact.

*(as written before J0)* 86 now. Reachable in this repo: d1 +1 (S2), d2 +3 (S1, S6), d3 +2 (S3,
S6), d4 +1 (S5), d6 +2 (S4), d7 +2 (S7) = **97 maximum**. Above 95 needs
ten of those eleven points to survive measurement. Four knobs have already
been killed by measurement in this programme; **expect some of these to
fall.** The loop reports the number the rows sum to (the arithmetic is
under test) — never the number this paragraph hoped for.

---

## Thread M — the upgrade

### M1 — a prompt-file agent is a graph (ADR 0152)

**Reproduce, RUN.** On the marlin clone at
`<scratchpad>/pilot-marlin`: `aef migrate --dir .` → `found 0 call
site(s)`. Eight agents, none seen.

**Change.**
- `PromptAgentNode` (put it where a node that only touches `Services` may
  live — `aef/reasoning/` or `aef/harness/`; **never a vendor import**):
  reads one agent file (frontmatter `name`/`description` + markdown body),
  calls `services.require_model_provider().complete(...)` with the body as
  the system message and `state.objective` as the user turn, writes the
  reply to `working_memory`, routes to `reflect`. `deterministic=False`,
  `SideEffect.EXTERNAL_CALL`, idempotency key from (agent name, objective).
  `--tools ""` stays: the agent's prompt runs, the agent's tools do not —
  say so in the docstring, it is the safety property.
- `aef migrate` discovers `.claude/agents/*.md` (and `.claude/skills/*/SKILL.md`
  as a second kind, if the same node serves — decide, say why). **One graph
  per agent**, `agents/migrated/<agent-name>/graph.py`, `graph_id` = the
  agent name, wired `prompt_agent → reflect → consolidate → END`. Fix F6's
  lesson: never several agents in one graph with dead nodes.
- **Zone A must contain the prompt file**, or the loop cannot propose to
  it (G0) and cannot bless it (ADR 0147/0149). Two designs; pick by *fewest
  changes to the containment-boundary code*, and record the other:
  (a) the repo runs with `--agent-root .claude/agents` and the generated
  graph lives under it (Claude Code reads only `*.md` there; a `.py` is
  inert — verify with the CLI, do not assume); (b) `ZonePolicy` takes
  several roots, every consumer goes through one `is_zone_a()`. Either
  way: **opt-in per repo** (`aef.yaml`), default unchanged (`agents/`), and
  `migrate`'s report says in words what it is adding to the loop's blast
  radius.
- G0 on a `.md` in Zone A: find out what `_scan` does with a non-Python
  file *by running it*. It must neither crash nor skip silently.

**Measure:** `aef migrate` on the clone finds 8 agents, writes 8 graphs;
`aef run agents.migrated.marlin_accela.graph --objective ... --config
aef.yaml` makes one harness call and returns text; `aef loop bootstrap` on
two inputs records two scenarios with a cassette. Zero model calls until
the measure step; ≤ 6 there.

### M2 — adopt into a repo that already has files (ADR 0153)

**Reproduce:** the marlin clone result above. Also: `aef adopt` in a repo
with `CLAUDE.md` present skips it — the adopter gets `AGENT_INTEGRATION.md`
and nothing pointing at it from the file their agent reads.

**Change.**
- Framework detection gains `prompt_files`: count of `.claude/agents/*.md`,
  skills, `AGENTS.md`, `.codex/`, `.github/copilot-instructions.md`,
  `.cursor/rules/*`. Report the counts. The checklist's "convert call
  sites" step becomes "run `aef migrate` — it registers your N prompt
  agents as graphs" when N > 0.
- **Append-within-markers** for files that exist: `CLAUDE.md`,
  `AGENTS.md`, `.github/copilot-instructions.md`, `.cursor/rules/aef.mdc`,
  `.gitignore` (the two bytecode patterns, ADR 0142). Block bounded by
  `<!-- aef:begin -->` / `<!-- aef:end -->` (a comment form the file type
  tolerates); re-running replaces *only* the block; **text outside the
  markers is byte-identical before and after — assert it with a hash in
  the test.** This extends ADR 0034/0040's never-overwrite rule: appending
  inside markers is not overwriting, and the ADR says so. Report `appended`
  as a third verb beside `wrote`/`skipped`.
- The generated `FIRST_DAY.md`/`LOOP.md` sequence for a prompt-file repo:
  `adopt → migrate → bootstrap --config → bless → doctor → cycle
  --cassette-miss live --config`, with the sentence that makes it honest:
  **a changed prompt cannot be scored from a cassette, so every gate pass
  of a prompt candidate is live, and the noise floor (S2) is the bar.**

**Measure:** re-run adopt on the clone: `detected framework: prompt_files
(8 agents, 5 skills, AGENTS.md, .codex)`; `AGENTS.md` carries the block;
its pre-existing bytes unchanged; second run idempotent. Zero model calls.

### M3 — Grok, and any harness after it (ADR 0154)

`GrokProvider` beside `ClaudeCodeProvider`/`CodexProvider` (ADR 0112's
shape): `grok --output-format json -m <model> [--agent/--agents]
<prompt>`, parse from the CLI's *actual* JSON — run it once with a
throwaway prompt, paste the shape into the ADR, never guess the field
names. Isolation flags: find Grok's equivalents of `--safe-mode`/`--tools
""` from its `--help`, and **measure input tokens with and without them**
the way ADR 0150 did. Live test opt-in twice, like the other two.

Then the scalable half: `CommandProvider` — argv template + output
extraction (a JSON pointer or "last line") from `aef.yaml`, so a harness
this loop has never seen (Copilot's CLI, tomorrow's) is **configuration an
owner writes, not code this repo guesses at.** Configure `GrokProvider`'s
own behaviour through it as the proof the template is sufficient. `impl:
command` in the factory; schema validates the template names the prompt
placeholder exactly once.

**Measure:** `grok` answers `OK` through the provider; input-token
numbers with/without isolation; `CommandProvider` reproducing the Grok
result from config alone. ≤ 10 calls.

### M4 — a proposer for prompts, and L4 measured (ADR 0157) — wave 2

`RuleBasedProposer` edits numeric constants: nothing to do in a `.md`.
`LLMProposer` rewrites whole files: works on prose, off by measurement for
code (ADR 0122) — *that measurement was of Python diffs against G5's drift
budget*; a prompt is a different object.

**Change:** `RuleBasedPromptProposer` — ACE's actual method, which the
knowledge layer already computes: take the highest-recurrence admissible
failure entry from `Services.knowledge` (ADR 0110's consolidated entries,
two-run rule intact), append it as one bullet under a `## Lessons (aef)`
section of the agent's prompt. Deterministic, no model call, one line of
drift. If the section exists, append; never rewrite existing bullets;
never exceed N bullets (config, default 5) — evict the stalest by
`runs_since_last_seen`. **The prompt never becomes the model's** — one
bullet is computed from records, provenance intact (ADR 0110's rule).

**Measure (L4, finally):** the marlin clone's `marlin-accela` graph, one
scenario that fails a check, admissible memory from bootstrap:
`--proposer rule_based_prompt` vs `--proposer llm`. Report: candidate
produced (y/n), lines changed, G5 drift consumed, gate verdict, calls.
≤ 30 calls. If neither produces a candidate the gates accept on one
scenario, that is the finding and M5 still runs.

### M5 — the acceptance test (ADR 0158) — wave 2

One `slow`, live-opt-in test that is this thread's definition of done:

**A clone of a real prompt-file repo goes `adopt` → `migrate` →
`bootstrap --config` → `bless` → `cycle --cassette-miss live --config` and
a candidate that edits a `.md` agent is proposed and gated on real
evidence.** Assert against `ledger.jsonl` (INGEST's rule); assert a verdict
was *reached*, not which — a test demanding acceptance can be met by
weakening G3. Build the fixture from a synthetic repo shaped like marlin
(three agents, `AGENTS.md`, `.codex/`) so CI can run the no-live half; the
live half runs against the clone with `AEF_LIVE_HARNESS=1`.

When it passes, retire `CLAUDE.md`'s "narrower and honest pitch" paragraph
and replace it with the measured one — one commit, before/after quoted.

### M6 — the pilot, on the clone (ADR 0163) — wave 3

INGEST L8 / READY K5, done the only safe way tonight: the **clone** at
`<scratchpad>/pilot-marlin`, never the owner's checkout, never pushed
anywhere. Full sequence; `aef run --record-runs` on five real objectives
drawn from marlin's own `AGENTS.md`; `aef loop harvest` (redaction on);
one cycle; read what the gates said. This is the "real signal" S7 claims
+2 on — real prompts, real harness, a repo nobody wrote to pass — and it is
*not* a third party; the last +3 stays unclaimed with the reason.

`--tools ""` means the agents produce text and touch nothing. Marlin's
prompts mention credentials and cloud resources; the redaction scan runs on
every recorded run and the ADR quotes its counts.

### M7 — the documents say what is now true — wave 3

`CLAUDE.md` (this repo), `AGENT_INTEGRATION.md`, the generated
`FIRST_DAY.md`/`LOOP.md`/`CLAUDE.md`: prompt-file agents are supported,
under which harnesses, at what live-call cost per gate pass, and the
`.gitignore`/`AGENTS.md` append behaviour. **Every claim from a command
that was run** (ADR 0148's rule; nine false claims were found that way).

---

## Thread S — the score

### S0 — J0, the independent re-score (ADR 0151) — wave 1, no live calls

BEYOND_90's J0, verbatim: a fresh agent with **no access to
`IMPROVE_LOG.md`, the ADRs, or any loop file**, given only the rubric's
weights table and dimension definitions, the code, the tests, and the
field references. Scores each dimension from code and tests alone, one
line of evidence per dimension naming the file. Its scores beside ours;
every disagreement resolved *in writing*; **a dimension it scores lower
takes the lower score unless the evidence it missed was undiscoverable —
which is then its own finding.** S-workers claim deltas on dimensions; J0
may move a base; deltas compose.

### S1 — I12, the ACE four-arm on the task metric (dim 2: 17 → 19; ADR 0155)

Runner armed and dry-run verified: `<scratchpad>/i12_ace_arms.py`, 42
calls at `--repeats 1`, 84 at `--repeats 2`. Copy it into the worker's
own scratch subdir. Falsifications as written in `TO_90_LOOP.md` — (c) ≤
(b) demotes ADR 0110's coverage result to a proxy; (d) ≤ (c) keeps LLM
reflection off; a gain smaller than the spread is not a gain.

### S2 — I13, the live noise floor and the planted regression (dim 1: 19 → 20; ADR 0156)

As written in `TO_90_LOOP.md`. Foreground, 600 s per repeat, each repeat's
result written to the worker's scratch as it completes. **The floor this
produces is the bar M4/M5/M6 use** — it is not only a rubric point.

### S3 — I14, the judge with the answer in evidence (dim 3: 8 → 9; ADR 0159) — wave 2

As written in `TO_90_LOOP.md`. 36 calls.

### S4 — J2, the archive earns its keep (dim 6: 8 → 10; ADR 0160) — wave 2

As written in `BEYOND_90_LOOP.md`. Do not raise the drift budget to get a
run to complete.

### S5 — J3, containment on by default (dim 4: 14 → 15; ADR 0161) — wave 2, no live calls

As written in `BEYOND_90_LOOP.md`. Promotion-path code: reproduce the
uncontained write first; touch neither `PolicyEngine`, the gates, nor
Tier-1; if it cannot be done without weakening something, stop and report
(HARD-STOP gate 2).

### S6 — J4, the two conflated signals (dim 2: +1, dim 3: +1; ADR 0162) — wave 2

As written in `BEYOND_90_LOOP.md`. **Leave both points unclaimed if the
rig cannot be built honestly.**

### S7 — J1, real signal, bounded (dim 7: 5 → 7; ADR 0164) — wave 3

Evidence is M6. +2 and no more.

---

## Waves, ownership, budget

Orchestrator owns `main`; workers on branches in isolated worktrees; each
worker gets **its own scratch subdirectory** (two workers collided on a
shared file tonight). Disjoint files per wave; the orchestrator resolves
`IMPROVE_LOG.md`/`docs/adr/README.md` by union in ADR order.

| wave | workers | files |
|---|---|---|
| 1 | S0, M1, M2, M3, S1, S2 | S0 report only · M1 `zones.py`, `migrate.py`, new node module, `harness/loop.py` zone consumers · M2 `adopt.py`, `adopt_loop.py`, `doctor.py`, `AGENT_INTEGRATION.md` · M3 `providers/`, `config/` · S1/S2 scratch + rubric rows |
| — | seam-hunt | the whole wave-1 diff, weighted at `migrate`↔`zones`↔`preflight`↔`candidate`, `adopt`↔markers↔idempotency, provider↔factory↔schema |
| 2 | M4, M5, S3, S4, S5, S6 | M4 proposer module + `harness/loop.py` proposer switch · M5 `tests/cli/test_prompt_repo_acceptance.py` + `CLAUDE.md` · S3–S6 scratch + rubric |
| — | seam-hunt | |
| 3 | M6, M7, S7 | clone only · docs · rubric |
| — | final seam-hunt, report | |

Live-call budget: S1 84 · S2 36 · S3 36 · S4 ≤ 100 · M1 ≤ 6 · M3 ≤ 10 ·
M4 ≤ 30 · M5 ≤ 30 · M6 ≤ 60 — **≈ 400**. Every live worker runs the quota
preflight first (ADR 0150's corrected argv), records calls made, and on a
rate limit **stops and reports blocked** rather than switching models or
guessing.

## Rules this loop adds

- **A flag's shape is not a flag's value** (ADR 0150). Any adapter to an
  external binary ships with a live test, opt-in, and the worker runs it.
- **A prompt candidate is gated live, or not at all.** Never let a cassette
  miss score a changed prompt as 0 and call that a rejection.
- **The prompt never becomes the model's.** Rule-based prompt edits are
  computed from records with provenance; an LLM proposer's edit to a prompt
  is a candidate like any other and earns nothing by being fluent.
- **Widening Zone A is a scope decision, not a default.** Opt-in per repo,
  named in the report, the default tree unchanged.
- **The clone is the pilot.** Nothing in `/Users/raptor/*` other than
  `aef-core` is written to. Ever.
- Workers: own scratch subdir; `PYTHONPATH=$PWD PATH=<repo>/.venv/bin:$PATH`;
  `--basetemp` outside the worktree; foreground with `timeout`; shasum-verified
  backups for every mutation revert; no `git checkout --` on uncommitted work.

## After each merge wave

Seam-hunt the diff. **Thirteen for thirteen.** Assume fourteen.

## Report

`docs/research/upgrade-<date>.md`: the survey table; each M increment
with the command that proves it on the clone; the acceptance test's
output; J0's scores beside ours with every disagreement resolved; the
rubric re-summed; every falsification that fired; calls made per worker;
what still requires the owner (Copilot's CLI, a third-party tenant, the
real pilot on a real checkout). Then stop.
