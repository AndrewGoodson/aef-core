# `keystone` — the full sequence, verbatim

A clone of `/Users/raptor/keystone` (READ-ONLY source; every command below ran
in the clone). 7 personas under `.claude/agents/`, 4 skills of its own,
`AGENTS.md`, `.codex/`, 192 tracked files, default branch `main`.

Provider throughout: `model_provider.impl: command` with
`argv: ["/bin/echo", "{system}", "{prompt}"]` — **zero live model calls**.

Target: graph `marlin-source`, persona `.claude/agents/source-agent.md`,
module `agents.migrated.marlin_source.graph`.

Absolute paths under the worker's scratch are elided as `<clone>` and
`<state>`; nothing else is edited.

## 1. `aef adopt --dir .`

```
$ (cwd=<clone>)
$ python -m aef.cli.main adopt --dir .
EXIT=0  elapsed=0.34s
--- stdout ---
detected framework: prompt_files (7 agents, 4 skills, AGENTS.md, .codex)
wrote <clone>/CLAUDE.md
wrote <clone>/aef.yaml
wrote <clone>/aef_adapter.py
wrote <clone>/AEF_MIGRATION_CHECKLIST.md
wrote <clone>/AGENT_INTEGRATION.md
wrote <clone>/AUTONOMY.md
wrote <clone>/.github/copilot-instructions.md
wrote <clone>/.cursor/rules/aef.mdc
wrote <clone>/LOOP.md
wrote <clone>/FIRST_DAY.md
wrote <clone>/agents/README.md
wrote <clone>/corpus/README.md
wrote <clone>/.github/workflows/loop-gate.yml
wrote <clone>/.github/workflows/loop-monitor.yml
wrote <clone>/.claude/skills/new-model-check/SKILL.md
appended aef block to <clone>/.gitignore (your bytes outside it are unchanged)
appended aef block to <clone>/AGENTS.md (your bytes outside it are unchanged)

migration checklist:
  1. Read the generated CLAUDE.md in full before writing any code.
  2. Fill in aef.yaml: objectives, tools.allow, policies, evaluator.suites.
  3. Identify your current entrypoint(s) — the function(s) that start an agent run.
  4. Put every node you convert under `agents/` — Zone A, the only tree the loop is allowed to propose changes to. `aef migrate` writes its generated graph to `agents/migrated/<agent>/graph.py`, which is inside Zone A, and names the zone of the path in its report; anywhere else is Zone C and, measured, a candidate touching it is rejected with `G0 rejected it: candidate touches paths outside Zone A` and the cycle exits 1 (ADR 0142, ADR 0143).
  5. Run `aef migrate --dir .` — it registers 7 prompt agents (`.claude/agents/*.md`) as graphs, one graph per agent at `agents/migrated/<agent>/graph.py` (the graph's `graph_id` is the agent's name), inside Zone A. There is no call site to convert: each node runs that agent's prompt as the system prompt of a single harness model call. The prompt runs; the agent's tools do not. NOTE which file the loop may then edit: the GRAPH is Zone A, the PERSONA `.md` is Zone C by default, so a candidate editing the prompt itself is rejected until you widen the agent root — `aef migrate --agent-root ...` is opt-in per repo and its report says what that adds to the loop's blast radius.
  6. Read `.claude/agents/*.md` and decide WHICH agents the loop should improve — one graph per agent means one loop target per agent, each with its own corpus, baseline and drift budget.
  7. Prove one harness call before the loop depends on it: `aef run <the generated module> --objective "..." --config aef.yaml --checkpoints-dir .aef-runs`. `model_provider.impl: claude_code` needs no API key.
  8. Add an Evaluator (start with aef.services.eval.rule_based.RuleBasedEvaluator).
  9. Run `aef doctor` to confirm the config and imports are wired correctly.
  10. Then read `FIRST_DAY.md` and run the sequence it documents: `aef migrate` -> `aef loop bootstrap --state <dir> --memory <file>` -> the tripwire line bootstrap prints -> `aef loop bless` -> `aef loop doctor` -> `aef loop cycle`. It is the only document that says what each step costs you and which failures exit 0 having done nothing.
  11. `aef adopt` appended `__pycache__/` and `*.py[cod]` to your existing `.gitignore`, inside a `# aef:begin` / `# aef:end` block — every byte you had is untouched and outside it, and re-running adopt replaces only that block. Delete the block if you ignore bytecode another way. Committed bytecode under your AGENT ROOT is Zone A content the loop never wrote, and G5 charges it as drift: measured 0.4675 of a 0.500 budget for a one-line candidate, against 0.0238 with the bytecode excluded (ADR 0142). The agent root is `agents/` by default and whatever you pass to `aef migrate --agent-root` otherwise (`.claude/agents/` for a prompt-file repo) — `aef adopt` runs before `aef migrate` and cannot know which you will choose, so both patterns are repo-wide and cover either.

--- stderr ---
```

## 2. `aef migrate --dir .`

```
$ (cwd=<clone>)
$ python -m aef.cli.main migrate --dir .
EXIT=0  elapsed=0.19s
--- stdout ---
scanned 21 Python file(s)
found 0 call site(s): 0 wrapped, 0 skipped


wrote <clone>/agents/migrated/graph.py
  Zone A (agents/**) — agent-writable, the only tree the self-rewiring loop may propose changes to

This generated the PLUMBING, not the semantics. Every wrapper passes
state.objective as a single prompt and stores the raw result; if your
function takes more than that, the node body is yours to finish.

found 7 prompt agent(s) under .claude/agents
  AGENT    marlin-azure  (.claude/agents/azure-agent.md)
            -> agents/migrated/marlin_azure/graph.py
            -> aef run agents.migrated.marlin_azure.graph --objective "..." --config aef.yaml
            graph_id='marlin-azure', wired prompt_agent -> reflect -> consolidate -> END
  AGENT    marlin-bug-hunter  (.claude/agents/bug-hunter-agent.md)
            -> agents/migrated/marlin_bug_hunter/graph.py
            -> aef run agents.migrated.marlin_bug_hunter.graph --objective "..." --config aef.yaml
            graph_id='marlin-bug-hunter', wired prompt_agent -> reflect -> consolidate -> END
  AGENT    marlin-implementer  (.claude/agents/implementer-agent.md)
            -> agents/migrated/marlin_implementer/graph.py
            -> aef run agents.migrated.marlin_implementer.graph --objective "..." --config aef.yaml
            graph_id='marlin-implementer', wired prompt_agent -> reflect -> consolidate -> END
  AGENT    marlin-orchestrator  (.claude/agents/orchestrator-agent.md)
            -> agents/migrated/marlin_orchestrator/graph.py
            -> aef run agents.migrated.marlin_orchestrator.graph --objective "..." --config aef.yaml
            graph_id='marlin-orchestrator', wired prompt_agent -> reflect -> consolidate -> END
  AGENT    marlin-reviewer  (.claude/agents/reviewer-agent.md)
            -> agents/migrated/marlin_reviewer/graph.py
            -> aef run agents.migrated.marlin_reviewer.graph --objective "..." --config aef.yaml
            graph_id='marlin-reviewer', wired prompt_agent -> reflect -> consolidate -> END
  AGENT    marlin-security  (.claude/agents/security-agent.md)
            -> agents/migrated/marlin_security/graph.py
            -> aef run agents.migrated.marlin_security.graph --objective "..." --config aef.yaml
            graph_id='marlin-security', wired prompt_agent -> reflect -> consolidate -> END
  AGENT    marlin-source  (.claude/agents/source-agent.md)
            -> agents/migrated/marlin_source/graph.py
            -> aef run agents.migrated.marlin_source.graph --objective "..." --config aef.yaml
            graph_id='marlin-source', wired prompt_agent -> reflect -> consolidate -> END

CONTAINMENT DEPENDS ON model_provider.impl, and each run records the one it got.
Each persona body becomes the system message of one completion; what that
completion may do is the provider's answer, not this command's (ADR 0169):
  claude_code  --tools "" (documented as "disable all tools"), --max-turns 1,
               --safe-mode, empty strict MCP config; persona in --system-prompt.
  grok         --tools "" is MEASURED to suppress nothing on 1.0.5 — the same argv
               read a planted file with one more turn allowed. --max-turns 1
               cancels such a run and the provider raises. No --safe-mode.
  codex        --sandbox read-only, no --tools, no --max-turns, no system flag —
               so the persona goes in the USER turn.
  command      whatever your argv template says; its isolation: list is YOUR
               unverified assertion, and with no {system} slot the persona goes
               in the USER turn.
  anthropic    no tools parameter is sent; persona in system=.
The frontmatter tools: key is read and never honoured under any of them. Every run
writes the provider's isolation set and the persona's channel to
working_memory["prompt_agent__containment"], and appends a
prompt_agent.persona_in_user_turn error when it was the user turn.

wrote 7 prompt agent graph(s):
  <clone>/agents/migrated/marlin_azure/graph.py
  <clone>/agents/migrated/marlin_bug_hunter/graph.py
  <clone>/agents/migrated/marlin_implementer/graph.py
  <clone>/agents/migrated/marlin_orchestrator/graph.py
  <clone>/agents/migrated/marlin_reviewer/graph.py
  <clone>/agents/migrated/marlin_security/graph.py
  <clone>/agents/migrated/marlin_source/graph.py

BLAST RADIUS — what the self-rewiring loop may now propose changes to.
  Zone A is 'agents'. The PROMPT AGENT graphs are inside it.
  The PERSONA FILES are NOT (.claude/agents/azure-agent.md is Zone C).
  So the loop may improve the generated GRAPH and never the PROMPT: a
  candidate touching a `.md` under .claude/agents is rejected by G0 with
  `candidate touches paths outside Zone A`, and `aef loop bless` archives a
  baseline that does not contain the persona.
  This is the default on purpose — widening the tree an agent may rewrite is
  a scope decision an owner makes, not one a migration makes for them.
  To widen it, re-run as
    aef migrate --dir . --agent-root .claude/agents
  and pass `--agent-root .claude/agents` to every `aef loop`
  command as well. Verified before it was offered: the Claude Code CLI
  enumerates only `*.md` under .claude/agents — a `.py` written
  there is inert to it, so the graphs can live beside the personas.

found 4 skill(s) and did NOT migrate any of them:
  SKILL    .claude/skills/county-onboard/SKILL.md
  SKILL    .claude/skills/marlin-cost-check/SKILL.md
  SKILL    .claude/skills/mcp-contract-check/SKILL.md
  SKILL    .claude/skills/new-model-check/SKILL.md   (aef's own — not yours)
  SKILL    .claude/skills/verify-and-ship/SKILL.md
  A skill is not an agent. Its body is instructions injected into a session
  already in progress, it presumes that session's task and tools, and it
  routinely points at bundled files a tool-less completion cannot open — so a
  graph built from SKILL.md would send an instruction sheet stripped of half
  its content and return something that looks like an agent's answer. It also
  has no objective of its own, and the objective is the user turn every
  generated graph sends. Named here rather than skipped in silence.

--- stderr ---
```

## 3. `aef loop bootstrap` (three objectives from keystone's AGENTS.md)

```
$ (cwd=<clone>)
$ python -m aef.cli.main loop bootstrap agents.migrated.marlin_source.graph --corpus corpus --inputs <clone>-inputs.json --state <state> --memory <state>/memory.jsonl --config aef.yaml
EXIT=0  elapsed=0.17s
--- stdout ---
recorded 3 scenario(s) in the train split
  WRONG   keystone-accela
  WRONG   keystone-ingestion
  passed  keystone-subscription
2 of 3 recorded run(s) FAILED: 0 raised or ended with a failed plan, 2 failed an owner check — the task metric, which fails without an error (ADR 0113).
  recording spent 3 live model call(s). Recording is the one pass that is SUPPOSED to be live: the gates replay these from each scenario's cassette and need no credential (ADR 0123).
  5 memory record(s) written to the durable store — what the graph's own reflect node observed, nothing bootstrap decided. `aef loop cycle --memory <the same file>` proposes from these.
  2 of them is/are a check-derived FAILURE record: the owner's check, evaluated against what the run produced (ADR 0174). A signature recurring in two distinct runs becomes a lesson (ADR 0110).

--- stderr ---
```

## 4. commit the adopted + migrated + bootstrapped tree

```
$ (cwd=<clone>)
$ git -c user.email=<committer> -c user.name=aef loop commit -qm adopted, migrated, bootstrapped
EXIT=0  elapsed=0.03s
--- stdout ---

--- stderr ---
```

## 5. `aef loop bless --agent-root .claude/agents`

```
$ (cwd=<clone>)
$ python -m aef.cli.main loop bless --repo . --state <state> --agent-root .claude/agents --agent-path .claude/agents/source-agent.md --graph-id marlin-source
EXIT=0  elapsed=0.21s
--- stdout ---
blessed .claude/agents/source-agent.md as baseline v1 for graph 'marlin-source'
  G5 now has a reference point to measure drift against.

--- stderr ---
```

## 6. `aef loop doctor` — all six obligations

```
$ (cwd=<clone>)
$ python -m aef.cli.main loop doctor --repo . --state <state> --agent-root .claude/agents --corpus corpus --agent-path .claude/agents/source-agent.md --graph-id marlin-source
EXIT=1  elapsed=0.14s
--- stdout ---
Loop readiness — 6 things you must supply

  [--] corpus + tripwire       3 scenario(s), 0 tripwire(s)
       fix: aef loop record <module> --corpus corpus --scenario-id tripwire-1 --objective '<a task beyond this agent>' --split validation --expected must_fail --working-memory '{"difficulty": 99}'. Without a tripwire the gates cannot detect reward hacking (ADR 0060).
  [OK] reflect node routed to  agents/migrated/marlin_source/graph.py: make_prompt_agent_node(route='reflect') builds a node that routes to it
  [--] observations            0 recorded run(s) at <state>/observations.jsonl
       fix: pass --observations from your production runs, then `aef loop monitor --observations <path>`
  [--] halt channel            none — a halt would tell nobody
       fix: set AEF_HALT_WEBHOOK in your environment (never in this repo)
  [OK] blessed baseline        1 archived version(s) of '.claude/agents'
  [OK] model calls visible     2 graphs scanned, none reaches a model SDK the harness cannot see

These are ADVISORY and this command is the only thing that reads them: `aef loop cycle` and `aef loop gate` will still run, and will print the unmet ones. Some enforce themselves later — G2/G3 refuse an empty corpus and G5 refuses without a blessed baseline — but a missing halt channel or an invisible model call stops nothing, which is why they are listed here.

--- stderr ---
```

## 7. `aef loop cycle --proposer rule_based_prompt --cassette-miss fail`

```
$ (cwd=<clone>)
$ python -m aef.cli.main loop cycle --repo . --state <state> --workdir <workdir> --agent-root .claude/agents --agent-path .claude/agents/source-agent.md --module agents.migrated.marlin_source.graph --entrypoint agents.migrated.marlin_source.graph:build_graph --corpus corpus --memory <state>/memory.jsonl --config aef.yaml --cassette-miss fail --proposer rule_based_prompt --graph-id marlin-source --build-command python -c pass
EXIT=1  elapsed=17.37s
--- stdout ---
  preflight: 3 of 6 obligation(s) unmet (corpus + tripwire, observations, halt channel). ADVISORY — this command does not refuse on them; run `aef loop doctor` for each fix.
  ledger verified: 1 entr(ies)
  proposed cycle-20260905T075124-prompt on local branch loop/cycle-20260905T075124-prompt (never pushed; proposer=rule_based_prompt)
  gated: reject — G2 rejected it: 3 previously-passing scenario(s) no longer pass (zero tolerance)
cycle verdict: proposed cycle-20260905T075124-prompt — Decision(disposition=<Disposition.REJECT: 'reject'>, reason='G2 rejected it: 3 previously-passing scenario(s) no longer pass (zero tolerance)', question='')

--- stderr ---
```

## 8. `ledger.jsonl`, `cycles.jsonl` and the candidate branch

```
kinds: ['blessed', 'proposed', 'gated', 'rejected']
== blessed {"archive_version": 1, "blessed": true}
== proposed {"base": "main", "head": "loop/cycle-20260905T075124-prompt", "paths": [".claude/agents/source-agent.md"]}
== gated
  evidence: 7 corpus pass(es) (21 scenario execution(s)): 1 candidate + 1 incumbent + 5 random control(s); 3/3 gated scenario(s) recorded from graph 'marlin-source'
  live_model_calls: False
  G0 pass  1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically scanned, no violations; 1 NOT statically scanned (not Python — an AST gate has nothing to say about them, and G1/G2/G5 judge them instead)
  G1 pass  1 build command(s) succeeded against the merged workspace
  G4 pass  no owner-only safety metadata declared by the candidate
  G5 pass  0/3 accepted in the last 7d; drift 0.008/0.500 from the blessed baseline
  G2 fail  3 previously-passing scenario(s) no longer pass (zero tolerance)
  grounded_in: ['checkfail-e50d3ac5cefec4f24c75053925b5a9bb (memory): failure:check:working_memory.prompt_agent:contains recurred', 'checkfail-fc861dc4f05ac12f3b6f4073160bcb41 (memory): failure:check:working_memory.prompt_agent:contains recurred']
== rejected {}
== cycles.jsonl
   {"at": "2026-09-05T07:51:41.828873+00:00", "command": "cycle", "proposed": true, "verdict": "proposed cycle-20260905T075124-prompt \u2014 Decision(disposition=<Disposition.REJECT: 'reject'>, reason='G2 rejected it: 3 previously-passing scenario(s) no longer pass (zero tolerance)', question='')"}
== current branch: main
== loop branches: ['loop/cycle-20260905T075124-prompt']
== diff main.. loop/cycle-20260905T075124-prompt
.claude/agents/source-agent.md
diff --git a/.claude/agents/source-agent.md b/.claude/agents/source-agent.md
index 3741783..2ee026a 100644
--- a/.claude/agents/source-agent.md
+++ b/.claude/agents/source-agent.md
@@ -63,3 +63,7 @@ schedule. A pass requires observable effects (count reconciliation, readback,
 and deduplicated replay) and non-zero failure-path tests;
 do not claim reconciliation until both manual runs, replay, and readback are
 evidenced.
+
+## Lessons (aef)
+
+- <!-- aef sig=failure:check:working_memory.prompt_agent:contains runs=2 --> 1 error(s) recorded; 0/0 tool call(s) failed. errors[0]: check failed: working_memory.prompt_agent does not contain a required substring the owner declared; observed 505 words, 3781 chars
```

## 9. `aef adopt --dir .` a second time — idempotency

```
$ (cwd=<clone>)
$ python -m aef.cli.main adopt --dir .
EXIT=0  elapsed=0.19s
--- stdout ---
detected framework: prompt_files (7 agents, 4 skills, AGENTS.md, .codex)
skipped <clone>/CLAUDE.md (already carries the current aef block)
skipped <clone>/aef.yaml (already exists)
skipped <clone>/aef_adapter.py (already exists)
skipped <clone>/.gitignore (already carries the current aef block)
skipped <clone>/AEF_MIGRATION_CHECKLIST.md (already exists)
skipped <clone>/AGENT_INTEGRATION.md (already exists)
skipped <clone>/AUTONOMY.md (already exists)
skipped <clone>/AGENTS.md (already carries the current aef block)
skipped <clone>/.github/copilot-instructions.md (already carries the current aef block)
skipped <clone>/.cursor/rules/aef.mdc (already carries the current aef block)
skipped <clone>/LOOP.md (already exists)
skipped <clone>/FIRST_DAY.md (already exists)
skipped <clone>/agents/README.md (already exists)
skipped <clone>/corpus/README.md (already exists)
skipped <clone>/.github/workflows/loop-gate.yml (already exists)
skipped <clone>/.github/workflows/loop-monitor.yml (already exists)
skipped <clone>/.claude/skills/new-model-check/SKILL.md (already exists)

migration checklist:
  1. Read the generated CLAUDE.md in full before writing any code.
  2. Fill in aef.yaml: objectives, tools.allow, policies, evaluator.suites.
  3. Identify your current entrypoint(s) — the function(s) that start an agent run.
  4. Put every node you convert under `agents/` — Zone A, the only tree the loop is allowed to propose changes to. `aef migrate` writes its generated graph to `agents/migrated/<agent>/graph.py`, which is inside Zone A, and names the zone of the path in its report; anywhere else is Zone C and, measured, a candidate touching it is rejected with `G0 rejected it: candidate touches paths outside Zone A` and the cycle exits 1 (ADR 0142, ADR 0143).
  5. Run `aef migrate --dir .` — it registers 7 prompt agents (`.claude/agents/*.md`) as graphs, one graph per agent at `agents/migrated/<agent>/graph.py` (the graph's `graph_id` is the agent's name), inside Zone A. There is no call site to convert: each node runs that agent's prompt as the system prompt of a single harness model call. The prompt runs; the agent's tools do not. NOTE which file the loop may then edit: the GRAPH is Zone A, the PERSONA `.md` is Zone C by default, so a candidate editing the prompt itself is rejected until you widen the agent root — `aef migrate --agent-root ...` is opt-in per repo and its report says what that adds to the loop's blast radius.
  6. Read `.claude/agents/*.md` and decide WHICH agents the loop should improve — one graph per agent means one loop target per agent, each with its own corpus, baseline and drift budget.
  7. Prove one harness call before the loop depends on it: `aef run <the generated module> --objective "..." --config aef.yaml --checkpoints-dir .aef-runs`. `model_provider.impl: claude_code` needs no API key.
  8. Add an Evaluator (start with aef.services.eval.rule_based.RuleBasedEvaluator).
  9. Run `aef doctor` to confirm the config and imports are wired correctly.
  10. Then read `FIRST_DAY.md` and run the sequence it documents: `aef migrate` -> `aef loop bootstrap --state <dir> --memory <file>` -> the tripwire line bootstrap prints -> `aef loop bless` -> `aef loop doctor` -> `aef loop cycle`. It is the only document that says what each step costs you and which failures exit 0 having done nothing.

--- stderr ---
```
