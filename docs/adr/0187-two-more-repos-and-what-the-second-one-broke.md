# ADR 0187: Two more repos, and the three things the second one broke

## Status

Accepted. Increment **M8** of `UPGRADE_LOOP.md` — generality beyond the one
repo everything was built against. Model: `claude-opus-5[1m]`. **Zero live
model calls**: every command on both clones ran with
`model_provider.impl: command` and `argv: ["/bin/echo", "{system}",
"{prompt}"]`, M5's offline form (ADR 0158). **No rubric dimension moves** —
adoption work claims no rubric point (INGEST_LOOP's rule). **No file under
`aef/` was modified**: every defect below is a finding with a reproduction,
pinned as a strict xfail, and handed to the fix wave.

ADR 0158 proved the documented sequence on a clone of `marlin`. One repo is
one repo. This runs the same sequence, unchanged, on clones of the other two
prompt-file repos in `UPGRADE_LOOP.md`'s survey — `keystone` and
`datamining` — and asks what was true of marlin rather than true of the
scaffold.

**Both repos completed the sequence and reached a gate verdict.** The
apparatus is general. Three defects surfaced, of which one is serious: on
`datamining`, `aef loop cycle` **exited 0 having done nothing**, which is
precisely the failure shape ADR 0139 exists to forbid and ADR 0149 closed for
a neighbouring default.

The full transcripts are `docs/research/second-repo/keystone-transcript.md`
and `docs/research/second-repo/datamining-transcript.md` — every command and
its real output, exit code and elapsed time. The isolated reproductions are
`docs/research/second-repo/reproductions.md`. All three artefacts were scanned
with `aef/harness/redaction.py`'s `RedactionPolicy` before being committed;
the only hit was this worker's own synthetic committer identity on the clone,
replaced with `<committer>` (`redaction labels matched = ()` after).

**The clones are the pilot.** `/Users/raptor/keystone` and
`/Users/raptor/datamining` were `git clone`d into the worker's scratch and
never written to; loop state lives outside both clones; nothing was pushed.

---

## What the two repos are

| | `keystone` | `datamining` | (`marlin`, ADR 0158) |
|---|---|---|---|
| personas under `.claude/agents` | 7, flat | 13, flat | 8, one nested |
| persona frontmatter | `name`, `description` | `name`, `description`, `tools`, `model` (12 of 13) | `name`, `description`, `tools` |
| persona `name:` vs filename | **differs** (`marlin-source` in `source-agent.md`) | matches | mostly matches |
| skills of its own | 4 | 6 | 5 |
| noise in the skills tree | **5 persona-shaped `.md` under `.../agents/`, 2 nested `SKILL.md`** | none | none |
| `AGENTS.md` | yes | yes | yes |
| `CLAUDE.md` | absent | **a symlink to `AGENTS.md`, tracked as one** | absent |
| `.codex/` | yes | no | yes |
| tracked files | 192 | 1109 | ~40 |
| default branch | `main` | **`azure-agent/uptime-monitoring`; no `main` exists** | `main` |

Every cell in bold is a shape no fixture in this repo had before today.

---

## `keystone` — the sequence, and it holds

Target: graph `marlin-source`, persona `.claude/agents/source-agent.md`,
module `agents.migrated.marlin_source.graph`. Three objectives drawn from
keystone's own `AGENTS.md` (Accela connectors, scheduled ingestion, the Azure
subscription boundary).

| step | exit | elapsed | outcome |
|---|---|---|---|
| `adopt --dir .` | 0 | 0.34 s | `prompt_files (7 agents, 4 skills, AGENTS.md, .codex)`; appended to `AGENTS.md` + `.gitignore`, wrote 15 files |
| `migrate --dir .` | 0 | 0.19 s | 7 found / 7 on disk, 7 graphs, no skip, no name refusal, no collision |
| `loop bootstrap` | 0 | 0.17 s | 3 scenarios, 2 owner-check failures, 5 memory records, 2 check-derived failures |
| `loop bless` | 0 | 0.21 s | baseline v1 for `marlin-source` |
| `loop doctor` | 1 | 0.14 s | 6 obligations, 2 green (advisory-unmet exit) |
| `loop cycle` | 1 | 17.37 s | proposed, gated, **REJECT at G2** |

Detection is exact:

```
detected framework: prompt_files (7 agents, 4 skills, AGENTS.md, .codex)
appended aef block to <clone>/.gitignore (your bytes outside it are unchanged)
appended aef block to <clone>/AGENTS.md (your bytes outside it are unchanged)
```

and the sentence is checkable rather than claimed:

```
== AGENTS.md
   HEAD bytes sha256 : 5e0b3791…77a5 (1518 bytes)
   now   bytes sha256: 2e4cd919…1149 (3758 bytes)
   original bytes are a verbatim PREFIX of the file now: True
   signed marker present: True
== .gitignore
   HEAD bytes sha256 : f4238f57…eaf0 (395 bytes)
   now   bytes sha256: 3619f5e3…7e0b (465 bytes)
   original bytes are a verbatim PREFIX of the file now: True
== numstat (added/removed)
5	0	.gitignore
36	0	AGENTS.md
```

Insertions only, on both.

**The keystone shape that matters.** `.claude/skills/verify-and-ship/` ships a
contract-lint corpus containing **five persona-shaped `.md` files under
directories literally named `agents/`**, plus two nested `SKILL.md` fixtures:

```
.claude/skills/verify-and-ship/fixtures/contract-lint/negative/agents/missing-input.md
.claude/skills/verify-and-ship/fixtures/contract-lint/positive/agents/fixture-agent.md
.claude/skills/verify-and-ship/fixtures/contract-lint/positive/skills/fixture-skill/SKILL.md
    (and four more)
```

`find .claude/skills -name SKILL.md` returns **6**; `discover_skills`'s
one-level glob returns **4**, and the detection line says 4. None of the five
persona-shaped files was migrated. This is the exact case that function's
docstring was written for (*"`rglob` found ten on the pilot instead of six:
two were fixtures inside a skill's own test corpus"*) — it is now asserted on
a real tree rather than described.

**`name:` is not the filename**, and nothing before today asserted it:
`source-agent.md` carries `name: marlin-source` and produces
`agents/migrated/marlin_source/graph.py` with `graph_id='marlin-source'`.
Seven for seven.

The cycle:

```
  proposed cycle-20260905T075124-prompt on local branch
    loop/cycle-20260905T075124-prompt (never pushed; proposer=rule_based_prompt)
  gated: reject — G2 rejected it: 3 previously-passing scenario(s) no longer pass
```

and the ledger, which is what is actually asserted:

```
kinds: ['blessed', 'proposed', 'gated', 'rejected']
== proposed {"base": "main", "head": "loop/cycle-…-prompt",
             "paths": [".claude/agents/source-agent.md"]}
== gated
  evidence: 7 corpus pass(es) (21 scenario execution(s)): 1 candidate + 1 incumbent
            + 5 random control(s); 3/3 gated scenario(s) recorded from graph 'marlin-source'
  live_model_calls: False
  G0 pass  1 file(s), 4 line(s), all Zone A; … 1 NOT statically scanned (not Python …)
  G1 pass  1 build command(s) succeeded against the merged workspace
  G4 pass  no owner-only safety metadata declared by the candidate
  G5 pass  0/3 accepted in the last 7d; drift 0.008/0.500 from the blessed baseline
  G2 fail  3 previously-passing scenario(s) no longer pass (zero tolerance)
```

**The G2 rejection is expected and is the proof the gates ran.**
`--cassette-miss fail` plus a changed prompt is a changed cassette key, so
every recorded call misses and every scenario fails. That is the
changed-prompt-cannot-replay rule, not a judgement of the lesson —
`UPGRADE_LOOP.md` says so itself. What it proves is that ADR 0170's prose
control cohort was **built and executed**: 21 real executions of a real graph,
1 candidate + 1 incumbent + 5 controls, over three scenarios.

The candidate branch's diff is exactly the persona, the repo is still on
`main`, and the bullet carries its provenance:

```
+## Lessons (aef)
+
+- <!-- aef sig=failure:check:working_memory.prompt_agent:contains runs=2 --> 1 error(s)
+  recorded; 0/0 tool call(s) failed. errors[0]: check failed: …
```

A second `adopt` is idempotent: same detection line (`7 agents, 4 skills`),
every file `skipped … (already exists)` or `(already carries the current aef
block)`.

---

## `datamining` — the sequence, and the one that stopped

Target: graph `dev-agent`, persona `.claude/agents/dev-agent.md`. Three
objectives drawn from datamining's own `AGENTS.md` (the background dev server,
stopping it, the test command before reporting done).

| step | exit | elapsed | outcome |
|---|---|---|---|
| `adopt --dir .` | 0 | 0.28 s | `prompt_files (13 agents, 6 skills, AGENTS.md)`; **`CLAUDE.md` skipped as a symlink** |
| `migrate --dir .` | 0 | 0.25 s | 13 found / 13 on disk, 13 graphs, no skip, no refusal, no collision |
| `loop bootstrap` | 0 | 0.20 s | 3 scenarios, 2 owner-check failures, 2 check-derived failures |
| `loop bless` | 0 | 0.31 s | baseline v1 for `dev-agent` |
| `loop doctor` | 1 | 0.15 s | 6 obligations, 2 green |
| `loop cycle` (default `--base`) | **0** | 0.18 s | **`no agent source at .claude/agents/dev-agent.md in main: no candidate`** |
| `loop cycle --base azure-agent/uptime-monitoring` | 1 | 63.22 s | proposed, gated, REJECT at G2 |

### What held, and is worth naming

**The symlink.** `datamining` tracks `CLAUDE.md` as a symlink blob pointing at
`AGENTS.md`. Adoption refuses it by name:

```
skipped <clone>/CLAUDE.md (a symlink, or under one — adoption never writes through a link)
```

This is the right call and it is load-bearing: `AGENTS.md` and `CLAUDE.md`
resolve to one inode, so appending to both would put **two aef blocks in one
file** and the second `adopt` would then have two signed markers to reconcile.
Measured after adopt: `AGENTS.md` grew 874 → 3117 bytes, original bytes a
verbatim prefix, `<!-- aef:begin sha256=` appears **once**, and `CLAUDE.md` is
still a symlink whose contents are byte-identical to `AGENTS.md`.

**The frontmatter keys.** 12 of datamining's 13 personas carry `model:`
(`opus`/`sonnet`/`haiku`) as well as `tools:`; `data-floor-lead` carries
`tools:` and no `model:`. `migrate` reports the difference per persona:

```
  AGENT    publisher  (.claude/agents/publisher.md)
            frontmatter read and NOT honoured: model, tools
  AGENT    data-floor-lead  (.claude/agents/data-floor-lead.md)
            frontmatter read and NOT honoured: tools
```

Read, reported, never obeyed — and the *set* differs where the frontmatter
differs, which a fixture with uniform personas cannot see. keystone's personas
carry neither key and the line is absent for all seven.

**`.claude/agent-memory/*.md`** (five files, datamining) are not under
`.claude/agents` and were not discovered. Correct.

**Scale.** 1109 tracked files versus keystone's 192 turned a 17-second gate
pass into a 63-second one. Nothing failed; it is recorded because the workspace
materialisation is linear in the tree and an adopter with a large repo should
expect it.

---

## F-M8-1 (HIGH) — a repo whose default branch is not `main` no-ops, and exits 0

`datamining`'s default branch is `azure-agent/uptime-monitoring`. There is no
`main` in the repository at all. Every step of the documented sequence
succeeded and said nothing about it; then:

```
$ aef loop cycle --repo . … --proposer rule_based_prompt --cassette-miss fail
  preflight: 3 of 6 obligation(s) unmet …  ADVISORY …
  ledger verified: 1 entr(ies)
  no agent source at .claude/agents/dev-agent.md in main: no candidate
cycle verdict: no agent source at .claude/agents/dev-agent.md in main: no candidate
EXIT=0
```

The persona is present, committed, and was blessed one step earlier. What is
absent is the ref.

### Reproduced in isolation

`docs/research/second-repo/reproductions.md`, `<scratch>/repro.py`: a scratch
repo with one persona, one `AGENTS.md`, one skill, whose **only** difference
from the passing case is `git init -b trunk`.

```
--- adopt      EXIT=0   detected framework: prompt_files (1 agent, 1 skill, AGENTS.md)
--- migrate    EXIT=0   found 1 prompt agent(s) under .claude/agents
--- bootstrap  EXIT=0   recorded 2 scenario(s) in the train split
--- bless      EXIT=0   blessed .claude/agents/one-agent.md as baseline v1
--- doctor     EXIT=1   [OK] reflect node … [OK] blessed baseline … [OK] model calls visible
--- cycle      EXIT=0   no agent source at .claude/agents/one-agent.md in main: no candidate
>>> ledger entries: 1 (blessed only)
>>> `main` exists: False
```

### Why it is worse than its size

`aef/harness/loop.py:1406`:

```python
if not config.repo.path_exists_at(config.base_ref, agent_path):
    lines.append(f"no agent source at {agent_path} in {config.base_ref}: no candidate")
    return CycleRun(harvested=harvested, lines=tuple(lines))
```

`path_exists_at` cannot distinguish an absent **file** from an absent **ref**,
so three things collapse into one sentence and one exit code:

1. the persona really is missing from the base ref (an operator error the
   message describes correctly),
2. the base ref does not exist (this case, where the message blames a file
   that is present),
3. and, separately, `no candidate` at exit 0 is *also* what a legitimate empty
   proposal prints (`no admissible failure memory: no candidate this cycle`,
   twelve lines above) — so an operator who has learned that `no candidate` is
   normal has no way to see that this one is not.

Nothing in `loop doctor`'s six obligations covers the base ref, so the
readiness command reports a repo ready that will no-op. And `aef/harness/zones.py`
already names this exact shape in a comment — *"`aef loop cycle` exited **0**
with `no agent source at agents/demo/graph.py`: ADR 0139's signature 'silently
inert' failure, reached from the documented defaults"* — for the default agent
**path**, which ADR 0149 fixed. The default base **ref** was left behind.

Pinned as `test_a_repo_whose_default_branch_is_not_main_does_not_no_op_silently`
(`xfail(strict=True)`). The test asserts what a fix must produce: `EXIT_USAGE`
and a message naming the missing ref, not exit 0 and a sentence about the
persona. Whether the fix should also *default* the base ref to the repo's own
HEAD branch rather than the literal `main` is a design question for the fix
wave — it is a behaviour change for every existing caller, and this worker does
not own `aef/`.

The workaround is real and was used: `--base azure-agent/uptime-monitoring`,
after which the cycle reaches a verdict identically to keystone's
(`G2 fail`, drift 0.004/0.500, `paths: [".claude/agents/dev-agent.md"]`).

## F-M8-2 (LOW) — `migrate`'s skill header does not count the list under it

Observed on **both** repos:

```
keystone:    found 4 skill(s) and did NOT migrate any of them:   … 5 SKILL rows
datamining:  found 6 skill(s) and did NOT migrate any of them:   … 7 SKILL rows
```

The header is `discover_adopter_skills` (the adopter's own, aef's
`new-model-check` excluded); the list is `discover_skills` (the raw listing,
aef's included and labelled `(aef's own — not yours)`). Each is deliberate on
its own — ADR 0172's D4 made the *count* exclude adopt's own output precisely
so it stops changing on every run, and `discover_skills`'s docstring says the
listing stays raw because migrate's job is to name every file it declined to
migrate. Their composition is a report that is wrong about itself.

Reproduced on a two-skill scratch repo: `found 2 skill(s)` over three rows.
Pinned as `test_migrates_skill_header_count_matches_its_own_listing`
(`xfail(strict=True)`). The cheap fix is to say `found 2 of your skill(s) (3
including aef's own)`; the choice is the fix wave's.

## F-M8-3 (MEDIUM) — the checklist points at a `CLAUDE.md` adopt just skipped

When `adopt` skips `CLAUDE.md` — because it is a symlink, which is
datamining's shape and the correct decision — the migration checklist it
prints in the same output still opens with:

```
skipped <repo>/CLAUDE.md (a symlink, or under one — adoption never writes through a link)
…
  1. Read the generated CLAUDE.md in full before writing any code.
```

On datamining the link happens to point at `AGENTS.md`, which *did* get the
block, so the instruction accidentally works. Reproduced with the link pointing
at `README.md` instead:

```
>>> CLAUDE.md content now: '# scratch\n'
>>> aef block in it     : False
>>> and yet the checklist's FIRST step says:
          1. Read the generated CLAUDE.md in full before writing any code.
```

The checklist is not conditioned on what adopt actually wrote, and step 1 is
the first thing a fresh coding-agent session in that repo reads. `CLAUDE.md`'s
own adoption section promises the generated file "is self-contained: a fresh
coding-agent session in that other repo, with no memory of this conversation,
can pick up the migration from it alone" — which is false whenever the file was
skipped. Pinned as
`test_the_checklist_does_not_point_at_a_claude_md_adopt_skipped`
(`xfail(strict=True)`).

---

## The test

`tests/cli/test_second_repo_acceptance.py`, mirroring M5's offline half on a
synthetic fixture built from what was observed above rather than from marlin:

- **7 personas, flat**, filenames `<role>-agent.md` carrying
  `name: harbor-<role>` — so the module, the graph id and the file on disk are
  three different strings, and the test asserts the generated tree against the
  `name:`, not the filename.
- **Frontmatter with no `tools:`** on any persona (keystone's shape), asserted
  by the *absence* of the `frontmatter read and NOT honoured` line. A separate
  test builds datamining's shape — `model:` + `tools:` on one persona, `tools:`
  alone on another — and asserts the reported key set differs per persona.
- **A skills tree carrying five persona-shaped `.md` under `agents/` and two
  nested `SKILL.md`**, asserted to be counted as neither: `3 + 1 = 4` skills in
  the detection line, five rows in migrate's listing (four adopter + one aef,
  labelled), and no `fixture_agent` module on disk.
- **A `CLAUDE.md` symlink to `AGENTS.md`**, asserted to be skipped, to survive
  as a symlink, and to leave exactly **one** `<!-- aef:begin sha256=` in the
  file both names resolve to.
- `.codex/`, hooks, a `settings.json`, an `AGENTS.md` with house rules whose
  bytes must survive at offset 0 with `removed == 0` on the numstat.
- The same offline provider, the same `--cassette-miss fail`, the same
  assertion that a verdict was **reached** and not which one, read from
  `ledger.jsonl`; every step's exit code asserted; and an explicit assertion
  that `no candidate` is *not* in the cycle's output, which is F-M8-1's shape.

Runtime 4.1 s for the full sequence; the whole file is 5.8 s.

## What "works on a repo nobody wrote to pass" now covers

**Three repos, one owner.** `marlin` (ADR 0158), `keystone` and `datamining`
(here) — none of which was written, shaped or edited to make this scaffold
work, and two of which were surveyed before any of this code existed. Across
them the sequence handles: 7, 8 and 13 personas; flat and nested trees;
`name:` matching and not matching its filename; frontmatter with `tools:`,
with `tools:`+`model:`, and with neither; a skills tree full of persona-shaped
fixtures; an `AGENTS.md` that quotes the markers and two that do not; a
`CLAUDE.md` that is absent and one that is a symlink; CRLF and LF
`.gitignore`s; `.codex/` present and absent; and 40, 192 and 1109 tracked
files. Detection, byte preservation, idempotency, discovery, sanitisation,
blessing, the six obligations and a real gate verdict hold on all three.

**What it does not cover, and the reason each is unclaimed:**

- **A third party.** All three repos have one owner, one house style, one
  set of conventions, and the same person wrote the personas and this
  scaffold's expectations of them. The correlated failure mode — a convention
  every one of these repos happens to share and no other repo does — is
  precisely the one three repos from one owner cannot detect. `UPGRADE_LOOP.md`
  leaves S7's last +3 unclaimed for this reason and it stays unclaimed.
- **A repo with SDK call sites.** All seven surveyed repos had zero. The
  call-site half of `migrate` is still exercised only by aef-core's own
  fixtures.
- **A live gate pass on either of these two.** Both halves here are offline by
  design (`/bin/echo`). ADR 0181 established that a live prompt-candidate gate
  pass works on the marlin clone with `gates.live_model_calls: true`; nothing
  here re-measures it, and the two repos' verdicts are therefore
  replay-artefact rejections, said so in as many words.
- **Non-`main` default branches**, until F-M8-1 is fixed: `datamining` needed
  `--base` passed by hand, and the survey did not record which of the other
  five repos would need the same.

## Green bar

`pytest -q`: **2722 passed, 7 skipped, 4 xfailed**; 2728 → **2733 collected**
(**+5, none removed**: 1 acceptance test, 1 frontmatter test, 3 strict xfails
pinning the findings). `mypy aef examples`: 135 files, clean. `ruff check .`:
clean. `ruff format --check aef tests examples`: 281 files, clean.
No file under `aef/` was modified.
