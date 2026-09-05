# The three findings, reproduced in isolation

Each is a scratch repo built by `<scratch>/repro.py` carrying ONLY the shape
under test — one persona, one `AGENTS.md`, one skill — so that nothing about
`keystone` or `datamining` other than the named difference is in the picture.
The same provider is used throughout (`impl: command`, `/bin/echo`), so there
are no live model calls here either.

All three are pinned as `xfail(strict=True)` in
`tests/cli/test_second_repo_acceptance.py`.

```
==============================================================================
F-M8-1  a repo whose default branch is not `main`
==============================================================================
--- adopt  EXIT=0
detected framework: prompt_files (1 agent, 1 skill, AGENTS.md)
--- migrate  EXIT=0
found 1 prompt agent(s) under .claude/agents
--- bootstrap  EXIT=0
recorded 2 scenario(s) in the train split
2 of 2 recorded run(s) FAILED: 0 raised or ended with a failed plan, 2 failed an owner check — the task metric, which fails without an error (ADR 0113).
--- bless  EXIT=1

--- doctor  EXIT=1
  [--] corpus + tripwire       2 scenario(s), 0 tripwire(s)
  [OK] reflect node routed to  agents/migrated/one_agent/graph.py: make_prompt_agent_node(route='reflect') builds a node that routes to it
  [--] observations            0 recorded run(s) at <scratch>/f1-state/observations.jsonl
  [--] halt channel            none — a halt would tell nobody
  [OK] blessed baseline        1 archived version(s) of '.claude/agents'
  [OK] model calls visible     2 graphs scanned, none reaches a model SDK the harness cannot see
--- cycle (base left at its default `main`)  EXIT=0
  preflight: 3 of 6 obligation(s) unmet (corpus + tripwire, observations, halt channel). ADVISORY — this command does not refuse on them; run `aef loop doctor` for each fix.
  ledger verified: 1 entr(ies)
  no agent source at .claude/agents/one-agent.md in main: no candidate
cycle verdict: no agent source at .claude/agents/one-agent.md in main: no candidate
>>> THE FINDING: exit 0 and no candidate; the branch `main`
>>> does not exist in this repo at all, and no step said so.
>>> ledger entries: 1 (blessed only)
>>> `main` exists: False
==============================================================================
F-M8-2  migrate's skill header count disagrees with its own listing
==============================================================================
header : found 2 skill(s) and did NOT migrate any of them:
listed : SKILL    .claude/skills/new-model-check/SKILL.md   (aef's own — not yours)
listed : SKILL    .claude/skills/skill-0/SKILL.md
listed : SKILL    .claude/skills/skill-1/SKILL.md
>>> THE FINDING: header says a count, the list under it has 3 rows.
==============================================================================
F-M8-3  the checklist tells the adopter to read a CLAUDE.md adopt skipped
==============================================================================
adopt  : skipped <repo>/CLAUDE.md (a symlink, or under one — adoption never writes through a link)
adopt  : 1. Read the generated CLAUDE.md in full before writing any code.
>>> CLAUDE.md content now: '# scratch\n'
>>> aef block in it     : False
>>> and yet the checklist's FIRST step says:
         1. Read the generated CLAUDE.md in full before writing any code.
```
