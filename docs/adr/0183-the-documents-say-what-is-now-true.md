# ADR 0183: The documents say what is now true, and nine of them did not

## Status

Accepted. Increment **M7** of `UPGRADE_LOOP.md`, wave 3. Model:
`claude-opus-5[1m]` (session default). **Zero live model calls** — every
command below ran against a `command`-provider `aef.yaml` whose argv is
`/bin/echo`, or is a filesystem read. **No rubric dimension moves** —
documentation work claims no rubric point (INGEST_LOOP's rule, unchanged since
ADR 0152).

M7's instruction was one sentence: *every claim from a command that was run*
(ADR 0148's rule; nine false claims were found that way the first time). This
increment applies it to the six documents an adopter and a fresh agent read as
instructions, against everything ADRs 0151–0180 established.

**Fourteen sentences were false or stale.** None of them made a test fail.
That is the finding, and it is the same shape as ADR 0151's: *asserted in prose
rather than shown by an artifact*. A document is the one artifact in this repo
with no green bar of its own, so the last section of this ADR adds one.

---

## The method

Nothing below is quoted from a source file. A read-only clone of a real
production repo — eight `.claude/agents/*.md` personas, five skills, its own
`AGENTS.md` and a `.gitignore`, no `anthropic`/`openai` call site anywhere —
was **copied** (the clone itself is never written to), stripped of a previous
adoption, and driven through the whole documented sequence.

The one substitution is the provider, and it is configuration rather than a
mock: `model_provider.impl: command` with
`argv: ["/bin/echo", "{system}", "{prompt}"]`. A real `CommandProvider`, a real
subprocess, zero API quota.

---

## The audit — every sentence, and what replaced it

### `CLAUDE.md` (this repo)

| # | the sentence | why it is false | what replaced it |
|---|---|---|---|
| 1 | "**LLM-backed reflection** and offline optimization are typed interfaces raising `NotImplementedError` (Phase 3/5)" | `aef/reasoning/llm_reflection.py` has had a body since ADR 0115, and the same file said so eleven paragraphs later | it is real, `reflection.impl: llm`, and **off by measurement** — four A/Bs (0115, 0155, 0171, 0175) |
| 2 | migrate writes "`prompt_agent -> reflect -> consolidate -> END`" | ADR 0179 made it four nodes with `retrieve` first — verified by reading the generated module | `retrieve -> prompt_agent -> reflect -> consolidate -> END`, with the ADR that changed it |
| 3 | "only `claude_code` sends `--tools "" --max-turns 1 --safe-mode`" read as *therefore only it is contained* | true but incomplete: `grok`'s identical `--tools ""` **suppresses nothing** (ADR 0169 measured it with a planted file) | the per-provider evidence, including the sentence that two CLIs spell it the same and one of them means it |
| 4 | "The model provider is real for **three** backends" | five (ADR 0154 added `grok` and `command`) | five, with what each was established from, and the derived `isolation` contract |
| 5 | "`knowledge_boost` … swept at 0/0.5/1/3 it changed no coverage number anywhere, so the benefit is consolidation, not ranking" | S1b: the knob demonstrably controls whether the store's only lesson reaches the model — **0/17 vs 10/17 in prompt** | the knob is real and moves no task metric; and ADR 0110's coverage result is a **proxy that S1b disproved for this corpus** |
| 6 | "**Measured, not asserted** … coverage falls 6→1" as the justification for the layer | the number holds; its use as a task-outcome predictor does not (ADR 0175) | the number, then the falsification, then why consolidation is kept anyway |
| 7 | "Landed 2026-09-03 by the improve loop … **50 → 79**" | 79 was a self-score; J0 re-scored the same code at 68 (ADR 0151) | `grep '^## Current'` on the rubric, pasted — **72 / 100** — plus what the 18 points went on |
| 8 | adopt "writes — without ever **overwriting** an existing file —" | five named files gain an appended block (0153), and the rule is enforced by `_verify_preserved` (0172) | never-**destroy**, executable rather than claimed, with the five files named |
| 9 | "It reads none of your existing code" | `detect_framework` import-scans Python and `detect_prompt_surface` counts prompt files | it reads your code only to *label* it, and converts nothing |

Added rather than corrected, because their absence was itself a false
impression: the four exit codes and what each means; the required
`--memory`/`--no-memory`; the file-path graph reference and the persona
`--agent-path` form; check-derived failure memory and the measured cost of
redacting the check's value; and the sentence that a prompt candidate **cannot
yet be accepted** on live evidence.

### `AGENT_INTEGRATION.md`

| # | the sentence | why it is false | what replaced it |
|---|---|---|---|
| 10 | "gain a block between `<!-- aef:begin -->` and `<!-- aef:end -->`" | the marker is **signed** since ADR 0172; a bare pair is inert prose | the signed form, what only-signed-is-adopt's buys, and the byte-level preservation check |
| 11 | "Four harnesses are wired … **The prompt runs; the agent's tools do not**" | the second half is a per-provider claim, false for `grok` and unverifiable for `command` (ADR 0169) | a five-row table: persona channel, isolation claimed, and *how it was established* for each |
| 12 | knowledge is "**Not reachable from `aef.yaml` yet** (see `MERGE_READY_LOOP.md` A1)" | `build_retriever(knowledge=...)` exists and `aef run --config` passes it — **closed by ADR 0118**, and the sentence outlived it by a release | reachable, plus ADR 0175's caveat so nobody cites the layer as a score gain |
| 13 | "writes **17** never-overwrite files" | the count is right; "never-overwrite" is not | 17, sourced — measured as 15 `wrote` + 2 `appended` on the pilot |

### `docs/roadmap.md` — the cited real-vs-stubbed authority

| # | the sentence | why it is false | what replaced it |
|---|---|---|---|
| 14 | "**Still stubbed:** an LLM-backed Critic/Judge" | same defect as #1, in the file the other two cite as authoritative | what the four A/Bs found, including ADR 0159's "the corpus cannot grade a judge" and ADR 0171's AUC 1.000 on one failure family, n=4 |
| — | the `knowledge_boost` sweep sentence and the `MERGE_READY_LOOP` A1 sentence | as #5 and #12 — the same two claims, in the authority | as above |

And six capabilities that were **absent** from the authority entirely, which
reads as "not built": the five providers and the `isolation` contract; prompt-
file agents end to end; the three proposers; the prose control cohort; the
lineage archive and containment-by-default; and the loop CLI's refusals and
exit codes. Plus the paragraph saying live gating of a prompt candidate does
not work today — the one capability the new section would otherwise imply.

### `corpus/README.md`

| # | the sentence | why it is false | what replaced it |
|---|---|---|---|
| 15 | *nothing at all about which model recorded what* | six validation scenarios are `claude-fable-5-1` and a judge A/B had already run across the mixture before S6 noticed (ADR 0162's defect 1) | a provenance section derived by a one-liner whose output is pasted |
| 16 | "**Nine** scenarios over `agents/demo` … five that pass and four that do not" | there are eleven; the two tripwires arrived after the sentence | eleven, with the command that counts them |

### The generated kit (`FIRST_DAY.md`, `LOOP.md`, the checklist, the appended block)

| # | the sentence | why it is false | what replaced it |
|---|---|---|---|
| 17 | the prompt-file "whole day" sequence | **it cannot propose a prompt candidate**: no `--agent-root`, so the persona is Zone C and G0 rejects any edit to it; no `--proposer rule_based_prompt`, so the numeric proposer runs against a file with no constants | the sequence that works, run below |
| 18 | "a cycle with no `--memory` reports `no memory store configured` and exits 0 every night" | it is **refused**, exit 2 (ADR 0165/0167) | the refusal, its exit code, and the journal + staleness alarm that now exist |
| 19 | "Exit codes: `0` escalated · `1` rejected · `2` halted" | there are four (ADR 0167) | the four, with what each means and `>= 2` as the CI rule |
| 20 | the pasted `bootstrap` output — "`2 of 4 recorded run(s) FAILED.`" | the line has two halves and three labels now (ADR 0174) | the real output of a real run, with `WRONG` and the check-derived records |
| 21 | "**No part of this has run against a repo aef-core did not write**" | ADR 0158's live half, and this increment's offline one | it has; what has **not** is acceptance |
| 22 | checklist step 5 / the appended block: "The prompt runs; the agent's tools do not" | as #11 — and this is the text that lands in *someone else's* `AGENTS.md` | migrate's report prints the measured table; the frontmatter is never obeyed, and the rest is the provider's answer |

---

## Every command that was run, with its real output

### 1. `aef adopt` into a populated prompt-file repo

```
$ aef adopt --dir .
detected framework: prompt_files (8 agents, 5 skills, AGENTS.md, .codex)
wrote .../CLAUDE.md
wrote .../aef.yaml
wrote .../aef_adapter.py
wrote .../AEF_MIGRATION_CHECKLIST.md
wrote .../AGENT_INTEGRATION.md
wrote .../AUTONOMY.md
wrote .../.github/copilot-instructions.md
wrote .../.cursor/rules/aef.mdc
wrote .../LOOP.md
wrote .../FIRST_DAY.md
wrote .../agents/README.md
wrote .../corpus/README.md
wrote .../.github/workflows/loop-gate.yml
wrote .../.github/workflows/loop-monitor.yml
wrote .../.claude/skills/new-model-check/SKILL.md
appended aef block to .../.gitignore (your bytes outside it are unchanged)
appended aef block to .../AGENTS.md (your bytes outside it are unchanged)
```

**15 wrote + 2 appended = 17.** That is where `AGENT_INTEGRATION.md`'s "17
files" number now comes from, and it is why "never-overwrite" was the wrong
word for two of them.

### 2. `aef migrate` under a widened root

```
$ aef migrate --dir . --agent-root .claude/agents
scanned 38 Python file(s)
found 0 call site(s): 0 wrapped, 0 skipped
...
found 8 prompt agent(s) under .claude/agents
  AGENT    marlin-accela  (.claude/agents/accela-agent.md)
            -> .claude/agents/migrated/marlin_accela/graph.py
            -> aef run .claude/agents/migrated/marlin_accela/graph.py --objective "..." --config aef.yaml
            (a file path, not '.claude.agents.migrated.marlin_accela.graph': no dotted module
            name exists under '.claude/agents', and `aef run` takes either form)
            graph_id='marlin-accela', wired prompt_agent -> reflect -> consolidate -> END
...
CONTAINMENT DEPENDS ON model_provider.impl, and each run records the one it got.
  claude_code  --tools "" (documented as "disable all tools"), --max-turns 1, ...
  grok         --tools "" is MEASURED to suppress nothing on 1.0.5 — the same argv
               read a planted file with one more turn allowed. ...
```

Two things came out of running it. The **file-path** sentence is real and no
generated document mentioned it, which is why the rewritten sequence uses that
form throughout. And migrate's own report still says
`wired prompt_agent -> reflect -> consolidate -> END` while the module it
writes is four nodes — see "Defects found and not fixed".

```
$ grep -n 'nodes=\|entry_node' .claude/agents/migrated/marlin_accela/graph.py
103:            "retrieve": make_retrieve_node(route="prompt_agent"),
104:            "prompt_agent": make_prompt_agent_node(
113:            "reflect": make_reflect_node(route="consolidate"),
114:            "consolidate": make_consolidate_node(route=END),
121:        entry_node="retrieve",
```

### 3. `aef loop bootstrap`, with owner checks

```
$ aef loop bootstrap .claude/agents/migrated/marlin_accela/graph.py --corpus corpus \
      --inputs inputs.json --state <s> --memory <s>/memory.jsonl --config aef.yaml
recorded 2 scenario(s) in the train split
  WRONG   accela-clearwater
  WRONG   accela-pinellas
2 of 2 recorded run(s) FAILED: 0 raised or ended with a failed plan, 2 failed an owner
  check — the task metric, which fails without an error (ADR 0113).
  recording spent 2 live model call(s). ...
  4 memory record(s) written to the durable store ...
  2 of them is/are a check-derived FAILURE record ... (ADR 0174).
```

This is the output the kit now pastes. The old block predates the `WRONG`
label, the split count and the check-derived records.

The recorded scenario also carries the containment record, which is what makes
the `command`-with-no-`isolation:` row in the rewritten table checkable:

```
"prompt_agent__containment": {"isolation": ["system_role"],
                              "persona_role": "system", "provider": "cassette"}
```

Nothing is claimed but the channel, exactly as ADR 0169 §2 says.

### 4. `bless`, and the `--graph-id` trap the sequence walked into

```
$ aef loop bless --repo . --state <s> --agent-root .claude/agents \
      --agent-path .claude/agents/migrated/marlin_accela/graph.py
blessed .claude/agents/migrated/marlin_accela/graph.py as baseline v1 for graph 'default'
```

and then, on the first cycle:

```
  --graph-id not given. The corpus at corpus records one graph, 'marlin-accela', but a
  blessed baseline already sits under the archive key 'default' ... WARNING: --proposer
  rule_based_prompt will drop this corpus's failure records as another graph's. To make the
  two namespaces agree, re-bless: `aef loop bless --graph-id marlin-accela ...`
  ...
  the proposer produced nothing from the available evidence: 2 record(s) dropped as
  another graph's scenario; no admissible failure record for this graph
EXIT=0
```

ADR 0176's warning did its job and named its own remedy. **The documented
sequence had no `--graph-id` in it**, so an adopter following it verbatim gets
this, exits 0, and has produced nothing — which is the exact failure shape
`LOOP.md`'s own opening paragraph exists to prevent. The rewritten sequence
passes `--graph-id` to both `bless` and `cycle`, and says why.

### 5. `aef loop doctor` with the PERSONA as `--agent-path`

```
$ aef loop doctor --repo . --state <s> --corpus corpus \
      --agent-root .claude/agents --agent-path .claude/agents/accela-agent.md
Loop readiness — 6 things you must supply

  [--] corpus + tripwire       2 scenario(s), 0 tripwire(s)
  [OK] reflect node routed to  .claude/agents/migrated/marlin_accela/graph.py:
       make_prompt_agent_node(route='reflect') builds a node that routes to it
  [--] observations            0 recorded run(s) at <s>/observations.jsonl
  [--] halt channel            none — a halt would tell nobody
  [OK] blessed baseline        1 archived version(s) of '.claude/agents'
  [OK] model calls visible     10 graphs scanned, none reaches a model SDK the harness
                               cannot see
```

ADR 0178's resolution and ADR 0158's F-M5-1 both visible in one report: the
persona resolves to its graph and says which file was read, and obligation 6
scans **ten** graphs under the widened root rather than one.

### 6. `aef loop cycle` — a prompt candidate, proposed and gated

```
$ aef loop cycle --repo . --state <s> --workdir <w> --corpus corpus \
      --entrypoint .claude/agents/migrated/marlin_accela/graph.py:build_graph \
      --graph-id marlin-accela --agent-root .claude/agents \
      --agent-path .claude/agents/accela-agent.md --proposer rule_based_prompt \
      --memory <s>/memory.jsonl --config aef.yaml --cassette-miss live \
      --build-command "/usr/bin/true"
  preflight: 3 of 6 obligation(s) unmet ... ADVISORY
  ledger verified: 2 entr(ies)
  proposed cycle-20260905T070646-prompt on local branch
    loop/cycle-20260905T070646-prompt (never pushed; proposer=rule_based_prompt)
  gated: reject — G2 rejected it: 2 previously-passing scenario(s) no longer pass
EXIT=1
```

The ledger:

```
== proposed  {"base": "main", "head": "loop/cycle-20260905T070646-prompt",
              "paths": [".claude/agents/accela-agent.md"]}   summary: 1 file(s), 4 line(s)
== gated
  evidence: 7 corpus pass(es) (14 scenario execution(s)): 1 candidate + 1 incumbent
            + 5 random control(s); 2/2 gated scenario(s) recorded from graph 'marlin-accela'
  G0 pass  1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically scanned,
           no violations; 1 NOT statically scanned (not Python ...)
  G1 pass  1 build command(s) succeeded against the merged workspace
  G4 pass  no owner-only safety metadata declared by the candidate
  G5 pass  0/3 accepted in the last 7d; drift 0.003/0.500 from the blessed baseline
  G2 fail  2 previously-passing scenario(s) no longer pass (zero tolerance)
  grounded_in: ['...(memory): failure:check:working_memory.prompt_agent:contains recurred',
                '...(memory): failure:check:working_memory.prompt_agent:contains recurred']
== rejected  {}
```

and the candidate's whole diff:

```
+## Lessons (aef)
+
+- <!-- aef sig=failure:check:working_memory.prompt_agent:contains runs=2 --> 1 error(s)
+  recorded; 0/0 tool call(s) failed. errors[0]: check failed:
+  working_memory.prompt_agent does not contain a required substring the owner declared;
+  observed 733 words, 5868 chars: '# Marlin Accela agent Purp…
```

**ADR 0158's shape, on the real pilot, at zero model cost**, plus the redaction
that ADR 0174 requires: the bullet never names `VERDICT:`. That is why the
documents now carry the cost of it — with the answer removed, ADR 0158
measured candidate and incumbent scoring identically.

### 7. The refusals

```
$ aef loop cycle ... (no --memory, no --no-memory)
error: a cycle without memory cannot propose — ... Pass --memory <file> ... or pass
--no-memory to say you mean that. Neither was given, and silence used to mean
--no-memory: this repo's own scheduled cycle was a no-op every night (ADR 0165), and
`aef loop run` was the same command with no guard at all (ADR 0167).
EXIT=2
```

```
$ aef loop monitor --repo . --state <s>
checked 0 merged change(s)
  cycles run: 2 (last 0.0 day(s) ago)
  last PROPOSED: 0.0 day(s) ago
  last KEPT/MERGED: never
```

### 8. Corpus provenance, derived rather than remembered

```
$ python -c "...agg by (split, models)..."
holdout     claude-fable-5-1       n= 2  sum-19-tram-depot .. sum-20-seed-bank
train       (no model call)        n= 6  boundary-3 .. tripwire-impossible-train
train       claude-fable-5-1       n=12  sum-01-kestrel-ferry .. sum-12-bell-recast
train       claude-opus-5[1m]      n= 8  sum-21-ardvey-ferry .. sum-28-kellet-branch
validation  (no model call)        n= 5  tripwire-impossible-val .. val-hard-5
validation  claude-fable-5-1       n= 6  sum-13-cider-press .. sum-18-heron-rookery
validation  claude-opus-5[1m]      n=11  sum-29-brindle-viaduct .. sum-39-coldbeck-society
```

`model_calls[].result.model` was on disk the whole time. Nothing read it.

### 9. Every emitted `aef` command still parses

```
$ (adopt into a fresh repo; extract every `aef ...` line from FIRST_DAY.md,
   LOOP.md, corpus/README.md and AGENT_INTEGRATION.md; parse each through
   `aef.cli.main.build_parser()`)
checked 55 failed 0
```

Up from 50, which is `tests/cli/test_pristine_adoption.py`'s floor.

### 10. The green bar

```
pytest -q            2692 passed, 7 skipped, 3 xfailed   (from 2679; +13 pin cases)
mypy aef examples    Success: no issues found in 135 source files
ruff check .         All checks passed!
ruff format --check  279 files already formatted
```

---

## The pins

`tests/test_prompt_surface.py` pinned the model guide's required blocks, its
forbidden patterns and the two verification instructions. It pinned nothing
about whether a document is **true** — which is how fourteen sentences went
stale with a green bar. Three are now pinned by sentence, in each surface that
carries them, plus the corpus provenance note:

1. **live gating is blocked today** (`CLAUDE.md`, `AGENT_INTEGRATION.md`,
   `FIRST_DAY.md`, `LOOP.md`) — an adopter who reads only "gated live" budgets
   for calls that will never be made.
2. **exit code 3** (`AGENT_INTEGRATION.md`, `LOOP.md`) — a document listing
   three codes teaches the reader to treat 3 as unknown.
3. **containment is per-provider**, by the phrase `suppresses nothing` (all
   four) — the fact a stamped sentence used to hide.
4. **the Fable recordings** (`corpus/README.md`), and the table is
   **re-derived from the scenario files inside the test**, so the document
   cannot drift from the corpus it describes.

Matched with whitespace collapsed: these are hard-wrapped markdown and a pin
that also pins where a line breaks fails on a reflow, which teaches whoever
hits it to delete the pin. The control is a surface that legitimately says none
of it (`AUTONOMY.md`), so a needle common enough to match everything cannot
slip in and pin nothing.

### One pin moved, deliberately

`tests/cli/test_adopt.py::test_the_kit_names_every_wired_harness_and_guesses_at_none`
asserted the literal `not** reproduced`. That pins one sentence's *markdown*
rather than the fact; the prompt-file section is a list now, and the same fact
reads "Not reproduced live". It asserts `not reproduced` case-insensitively,
and gains `suppresses nothing` — the half of ADR 0169 that a stamped
containment sentence used to hide.

Two other pins constrained the rewrite and were **not** moved, because both
were right. `test_the_kit_carries_the_prompt_file_sequence_and_the_sentence_that_makes_it_honest`
requires the six steps in order inside the section (a prose mention of
`aef loop doctor` before the block broke it — the paragraph moved to after the
block, where it belongs as an explanation of it) and requires the literal
sentence *"every gate pass of a prompt candidate is a LIVE pass"*, which is
true and is now followed by the qualifier rather than replaced by it. Neither
file is this worker's, and neither needed to be.

### Mutations

Against `tests/test_prompt_surface.py`. Perturb, RUN, restore from a byte
backup, prove the sha256 unchanged; control green before and after.

| # | mutation | result |
|---|---|---|
| M1 | drop the live-gating sentence from `CLAUDE.md` | CAUGHT |
| M2 | drop the exit-3 row from the rendered `LOOP.md` | CAUGHT |
| M3 | turn grok's "suppresses nothing" into "works" | CAUGHT |
| M4 | delete the exhausted-quota note from `corpus/README.md` | CAUGHT |

4 of 4. M4 first read MISSED because the phrase occurs twice and only the first
was perturbed — the mutation was wrong, not the pin, and the corrected
mutation caught it.

---

## Defects found and not fixed (other workers' files)

1. **`aef migrate`'s report says `wired prompt_agent -> reflect -> consolidate
   -> END`** while the module it writes in the same run has four nodes with
   `retrieve` as the entry (both quoted above). `aef/cli/migrate.py` is not
   this worker's file. This is the ADR 0091 shape once more: one fact, two
   owners, kept correct in one. The generated docstring and the documents are
   now right; the report line is not.
2. **The documented prompt-file sequence had no `--graph-id`**, which is fixed
   in the documents here. The underlying double life of that flag is stated in
   ADR 0176 and explicitly *not* resolved there: `LoopConfig` still has one
   field for two namespaces. Until it has two, every prompt-file adopter meets
   this, and the warning is what saves them.
3. **`aef loop bootstrap` printed no `must_fail` tripwire suggestion** on a run
   where both scenarios were `WRONG` rather than raised. `FIRST_DAY.md` §4 says
   "bootstrap prints the line and never runs it". Not investigated further —
   it may be correct (a wrong answer is not evidence a task was impossible) —
   but the document and the observed behaviour disagree on a repo of exactly
   the shape the document is for.

## Consequences

- **A document is now something that can fail.** Four facts a reader acts on
  are pinned by sentence and one of them by re-derivation from the data. That
  is a small number against fourteen defects, and it is deliberate: pinning
  every sentence would make every edit a test change, and the pins would be
  deleted rather than moved. These four were chosen because losing one costs
  money, a wrong CI decision, or a false containment belief.
- **The generated prompt-file sequence can now propose.** Before this it could
  not, on any repo, for two independent reasons — and it had been through
  three ADRs and a parser-level test, because every command in it *parsed*.
  ADR 0148's rule is that a command was RUN; this is the case that shows
  parsing is not running.
- **"No part of this has run against a repo aef-core did not write" is
  retired.** What replaced it names what has not: nobody has yet seen a prompt
  candidate pass all six gates, and ADR 0158's two defects are why.
- **The corpus's model provenance is written down once.** It cannot be
  re-derived for the Fable twenty if the recordings are ever lost, because that
  quota is exhausted.
