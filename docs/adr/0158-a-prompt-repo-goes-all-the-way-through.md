# ADR 0158: A prompt-file repo goes all the way through, and where it stops

## Status

Accepted. Increment **M5** of `UPGRADE_LOOP.md` — the M-thread's definition of
done. Model: `claude-opus-5[1m]`. **15 live model calls** (budget ≤ 40). **No rubric
dimension moves** — adoption work claims no rubric point (INGEST_LOOP's rule).

M5 asked for one thing:

> A clone of a real prompt-file repo goes `adopt` → `migrate` → `bootstrap
> --config` → `bless` → `cycle --cassette-miss live --config` and a candidate
> that edits a `.md` agent is proposed and gated on real evidence.

It does. `tests/cli/test_prompt_repo_acceptance.py` runs that sequence twice —
offline against a synthetic repo shaped like the marlin pilot, and live against
a copy of the pilot clone — and asserts against `ledger.jsonl` that a candidate
whose diff is **one `.md` under `.claude/agents`** was proposed and that the
gates reached a **verdict**. Not which verdict: a test demanding acceptance can
be met by weakening G3 (ADR 0139's rule; ADR 0170's fixture B is the same
argument).

Three things it also found, and they are the reason this ADR is not one
paragraph long: the verdict both halves reach is **G2 reject**, and in neither
half is that a judgement of the prompt. Offline it is the changed-prompt-
cannot-replay rule. Live it is a defect — the gate's sandbox worker cannot log
in. The measurement the gate could not make was made instead with `aef loop
score`, in-process and live, and **it falsifies M4's result**.

---

## The offline half — CI runs it, no credential

The fixture is a synthetic repo with marlin's *shape* and none of its content:
three personas under `.claude/agents/` (one nested in `sub/`, because
discovery recurses and `detect_prompt_surface` globbed one level until ADR
0172's R4), an `AGENTS.md` carrying the adopter's own prose which **quotes the
bare markers** with house rules between them (0172's R2), a **CRLF**
`.gitignore` (0172's R1), a `.codex/`, and a skill.

The one substitution is the provider, and it is configuration rather than a
mock: `model_provider.impl: command` with
`argv: ["/bin/echo", "{system}", "{prompt}"]` and `system_argv: ["{system}"]`.
A real `CommandProvider`, a real subprocess, the persona in the system
channel — and `aef run` confirms it:

```
"working_memory": {
  "prompt_agent": "You are the Harbor connector specialist ... May the Clearwater connector be enabled?",
  "prompt_agent__containment": {"provider": "command",
     "isolation": ["no_project_context","no_tools","single_turn","system_role"],
     "persona_role": "system"}
}
```

### Step by step, with what each step asserts

**1. `adopt` into a populated repo.**

```
detected framework: prompt_files (3 agents, 1 skill, AGENTS.md, .codex)
appended aef block to .../AGENTS.md (your bytes outside it are unchanged)
appended aef block to .../.gitignore (your bytes outside it are unchanged)
```

and the sentence is now checkable rather than claimed:

```
$ git diff --numstat -- AGENTS.md .gitignore
41  0  AGENTS.md
5   0  .gitignore
```

Insertions only. `AGENTS.md`'s original bytes are at offset 0; `RULE 7` and
`RULE 8` each appear once; the quoted `<!-- aef:begin -->` is untouched prose;
adopt's own marker is the signed form `<!-- aef:begin sha256=… -->`. The
`.gitignore` block is rendered in the file's own ending:
`# aef:begin sha256=…\r\n__pycache__/\r\n*.py[cod]\r\n# aef:end\r\n`.

**2. `migrate`.** Three graphs, one per persona, the nested one included, and
every run command the report prints is `shlex`-parsed and checked to be an
`aef run <target> --config aef.yaml` this CLI accepts (ADR 0168's M4 was a
printed command that could not run at all).

**3. `bootstrap --memory --config`.**

```
recorded 3 scenario(s) in the train split
  WRONG   harbor-clearwater
  WRONG   harbor-pinellas
  passed  harbor-preconditions
2 of 3 recorded run(s) FAILED: 0 raised or ended with a failed plan, 2 failed an
  owner check — the task metric, which fails without an error (ADR 0113).
  5 memory record(s) written to the durable store ...
  2 of them is/are a check-derived FAILURE record ... (ADR 0174). A signature
  recurring in two distinct runs becomes a lesson (ADR 0110).
```

Both failure records carry `failed_checks:
["check:working_memory.prompt_agent:contains"]` under two distinct `run_id`s.
**This is M4b's increment doing the job M4 could not**: ADR 0157 had to
synthesise its evidence because a prompt agent that answers cannot produce
failure memory. It can now.

**4. `bless --agent-root .claude/agents`.** `entry.json` carries
`agent_root: ".claude/agents"` (ADR 0167's F7 — a baseline that did not record
its own tree charged the first candidate 1.000 of a 0.500 budget), and its six
`file_digests` are all under that root and include the persona.

**5. `doctor`,** twice. Once with the persona as `--agent-path` (what the
proposer needs), and once with it defaulted, which is refused:

```
error: `loop doctor` was given --agent-root '.claude/agents' and --agent-path
'agents/migrated/graph.py', and 'agents/migrated/graph.py' is not inside
'.claude/agents'. It was left at its default, and that default names a file
under the DEFAULT root 'agents'. ... EXIT=2
```

**6. `cycle --proposer rule_based_prompt --cassette-miss fail`.** The ledger:

```
== blessed   {"archive_version": 1, "blessed": true}
== proposed  {"base": "main", "head": "loop/cycle-…-prompt",
              "paths": [".claude/agents/accela-agent.md"]}
== gated
  evidence: 7 corpus pass(es) (21 scenario execution(s)): 1 candidate +
            1 incumbent + 5 random control(s); 3/3 gated scenario(s) recorded
            from graph 'harbor-accela'
  G0 pass  1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically
           scanned, no violations; 1 NOT statically scanned (not Python …)
  G1 pass  1 build command(s) succeeded against the merged workspace
  G4 pass  no owner-only safety metadata declared by the candidate
  G5 pass  0/3 accepted in the last 7d; drift 0.012/0.500 from the blessed baseline
  G2 fail  3 previously-passing scenario(s) no longer pass (zero tolerance)
  grounded_in: ['…(memory): failure:check:working_memory.prompt_agent:contains recurred',
                '…(memory): failure:check:working_memory.prompt_agent:contains recurred']
== rejected  {}
```

and `cycles.jsonl`:

```
{"at": "…", "command": "cycle", "proposed": true,
 "verdict": "proposed cycle-… — Decision(disposition=<Disposition.REJECT: 'reject'>, …)"}
```

The candidate branch's diff is exactly `.claude/agents/accela-agent.md`, the
repo is still on `main`, and the appended bullet carries its provenance:
`- <!-- aef sig=failure:check:working_memory.prompt_agent:contains runs=2 -->
1 error(s) recorded; …`.

**ADR 0139's failure shape is gone.** Every step's exit code is asserted; no
step exited 0 having done nothing; the cycle journalled itself while
rejecting.

### What the offline verdict is, and is not

`--cassette-miss fail` + a changed prompt = a changed cassette key = three
misses = three failed nodes = G2 reject. That is the replay rule, not the
lesson. `UPGRADE_LOOP.md` says so itself ("Never let a cassette miss score a
changed prompt as 0 and call that a rejection"), which is why the test asserts
a verdict was *reached* and says in a comment which artifact produced it.

**G3 therefore does not run offline**, because the pipeline stops at G2's
rejection. What *is* proved offline is that ADR 0170's prose cohort was built
and executed — `1 candidate + 1 incumbent + 5 random control(s)`, 21 real
executions of a real graph — which before 0170 read *"the candidate changed no
Python file, so there is nothing to mutate for a control cohort"*. Reaching G3
offline needs a cassette pre-populated for all seven personas, which ADR 0170's
own fixtures do directly and no CLI command does.

---

## The live half — a copy of the pilot clone, `AEF_LIVE_HARNESS=1`

Quota preflight with ADR 0150's corrected argv: `is_error: false`,
`result: "OK"`, `usage.input_tokens: 2`, model `claude-opus-5[1m]`. **1 call.**

The read-only clone is copied first (`UPGRADE_LOOP.md`'s rule: nothing outside
`aef-core` is written to, and a read-only clone is not an exception). Same
sequence, `impl: claude_code`, `model: claude-opus-5`, two inputs, the owner
check of ADR 0157.

**A measurement about the objective, made by getting it wrong first.** The
first attempt phrased both objectives as *"…then end with a machine-readable
verdict line the ingestion runbook can parse."* The model duly wrote
`VERDICT:` for Clearwater, the check passed, only one run failed, and no
signature recurred. **2 calls, spent on learning that a check embedded in its
own prompt is not a check.** Rephrased as a plain domain question — which is
what ADR 0157 always said it was — both runs fail it.

```
2 of 2 recorded run(s) FAILED: 0 raised or ended with a failed plan,
  2 failed an owner check …
  2 of them is/are a check-derived FAILURE record …
```

**2 calls.** Then the cycle, `--cassette-miss live`:

```
  ledger verified: 1 entr(ies)
  proposed cycle-20260905T042310-prompt on local branch
    loop/cycle-20260905T042310-prompt (never pushed; proposer=rule_based_prompt)
  gated: reject — G2 rejected it: 2 previously-passing scenario(s) no longer pass

evidence: 7 corpus pass(es) (14 scenario execution(s)): 1 candidate + 1 incumbent
          + 5 random control(s); 2/2 gated scenario(s) recorded from graph 'marlin-accela'
G0 pass  1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically scanned,
         no violations; 1 NOT statically scanned (not Python …)
G1 pass  1 build command(s) succeeded against the merged workspace
G4 pass  no owner-only safety metadata declared by the candidate
G5 pass  0/3 accepted in the last 7d; drift 0.007/0.500 from the blessed baseline
G2 fail  2 previously-passing scenario(s) no longer pass (zero tolerance)
grounded_in: ['…failure:check:working_memory.prompt_agent:contains recurred', …]
kinds: ['blessed', 'proposed', 'gated', 'rejected']

diff --git a/.claude/agents/accela-agent.md b/.claude/agents/accela-agent.md
@@ -106,3 +106,7 @@
+
+## Lessons (aef)
+
+- <!-- aef sig=failure:check:working_memory.prompt_agent:contains runs=2 -->
+  1 error(s) recorded; 0/0 tool call(s) failed. errors[0]: check failed:
+  working_memory.prompt_agent does not contain a required substring the owner
+  declared; observed 85 words, 638 chars: 'No — `blocked`. Enabling req…
```

**Verdict reached: REJECT. Drift consumed: 0.007 of 0.500.**

**Calls, counted honestly.** 15 requests reached the API: 1 quota preflight,
8 across four `bootstrap` runs (2 of them spent on the objective-phrasing
mistake above, 2 on a run that died on a missing git committer identity),
2 environment probes, 4 paired live scoring. A further **29 `claude -p`
invocations inside the gate exited in ~30 ms with `Not logged in` and cost
nothing** — which is the next finding.

And the whole gate pass finished in **20 seconds**, which is how the next
finding was noticed: fourteen Opus calls do not take twenty seconds.

---

## F-M5-3 (HIGH) — the gate's sandbox worker is not logged in

### Reproduced, twice, and narrowed to one variable

First inside the real path, one scenario through `run_corpus_isolated` — the
function G2 uses — with the incumbent persona and then with the candidate's:

```
== incumbent persona, cassette_miss=live
   accela-clearwater: failure=None                      # the cassette HIT; no call made
== CANDIDATE persona, cassette_miss=live
   accela-clearwater: failure='NodeEvaluationError: ModelProviderError: claude
     exited 1: …"is_error":true,…"result":"Not logged in · Please run /login"…'
```

Then in isolation, with no aef code in the picture at all
(`<scratch>/repro_login.py`):

```
allowlist: ['HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'PATH', 'TMPDIR', 'TZ']
scrubbed (what the worker gets):  rc=1 is_error=True  result='Not logged in · Please run /login'
allowlist + USER only:            rc=0 is_error=False result='OK'
```

`aef/harness/sandbox.py::DEFAULT_ENV_ALLOWLIST` has no `USER`. `HOME` is
there, so this is not the config directory; it is whatever the CLI resolves
the account with. One variable, and adding it alone restores the login.

### Why it matters more than its size

`ClaudeCodeProvider`'s entire premise (ADR 0112, and the first line of the
generated `aef.yaml`) is that **the coding agent's own login is the
credential — no API key anywhere**. That premise holds in the parent process,
which is why `bootstrap` records live without complaint. It does not hold in
the worker, which is the only place the *gates* execute a candidate. So:

- every `--cassette-miss live` request from a changed prompt fails,
- G2 reports it as `N previously-passing scenario(s) no longer pass`, with the
  worker's actual message dropped on the way (`g2_outcome.py`), and
- `UPGRADE_LOOP.md`'s rule — *a prompt candidate is gated live or not at
  all* — resolves to **not at all**, on every repo, today.

It is a one-word change in a file this worker does not own, so it is reported
rather than made, and pinned as
`test_the_sandbox_env_allowlist_carries_what_the_harness_login_needs`
(`xfail(strict=True)`).

The fix wants a moment's thought rather than a one-word patch: the allowlist
exists so that *no credential is inherited* (`sandbox.py`'s own docstring), and
adding `USER` is precisely how a credential gets inherited here. That is the
right answer for `claude_code` — the whole design is that the operator's login
is the credential — and it should be a deliberate, documented widening rather
than a typo correction, because it means the shadow run can spend the
operator's quota.

## F-M5-2 (HIGH) — the credential-free provider cannot cross the boundary either

`_live_provider_from_base_ref` (`aef/harness/loop.py`) puts
`{"impl", "model"}` on the wire and nothing else; `node_worker._configure`
rebuilds `ModelProviderConfig(impl=…, model=…)`. For `impl: command` the schema
refuses, correctly:

```
== live_provider = the base ref's {impl: command, model: stub-echo}
   harbor-clearwater: failure="IsolationError: worker refused configuration:
     configure failed: ValidationError: … model_provider.impl is 'command' but no
     `command:` block is present. There is no argv template to run; see docs/adr/0154."
   (all 3 scenarios, every cohort member)
== live_provider = None (cassette_miss=fail)
   harbor-clearwater: failure=None   (all 3 pass)
```

So the one provider that needs **no credential**, and the one ADR 0154 points
every new adopter at ("Copilot's CLI is configured this way… and every harness
released after this file was written"), is the one provider a live gate pass
cannot use. Together with F-M5-3: **no provider serves a live cassette miss
inside the gates today.** Pinned as
`test_the_live_provider_spec_can_rebuild_the_credential_free_provider`
(`xfail(strict=True)`).

## F-M5-1 (MEDIUM) — obligation 6's every-graph scan is unreachable where it was needed

G1b (ADR 0168) widened obligation 6 from one `agent_path` to every graph
`discover_graph_files` finds, passed when `--agent-path` was **left at its
default**. G1a (ADR 0167) made a defaulted `--agent-path` a hard refusal
whenever `--agent-root` is **non-default**. Their intersection is every
widened-root repo — the whole class ADR 0152 exists to serve.

```
discover_graph_files under the widened root:
    aef_adapter.py
    agents/migrated/graph.py
    .claude/agents/migrated/harbor_accela/graph.py
    .claude/agents/migrated/harbor_reviewer/graph.py
    .claude/agents/migrated/harbor_source/graph.py
scan_all_graphs=False: 1 graph scanned, none reaches a model SDK …
scan_all_graphs=True:  5 graphs scanned, none reaches a model SDK …
```

The capability is there; the CLI cannot ask for it. Pinned as
`test_obligation_six_scans_every_graph_under_a_widened_root`
(`xfail(strict=True)`).

## Two findings handed to this worker mid-run, both hit and worked around

**R1** (third seam hunt): `--entrypoint` is loaded by
`scenario_runner.load_graph` / `node_worker.load_graph`, which still call
`importlib.import_module`, so a graph at `.claude/agents/migrated/<name>/graph.py`
cannot be loaded by either spelling. Hit directly — the first two runs of this
sequence rejected at G2 with `1 error(s)` and no reason — and worked around the
way M4 did: `aef migrate` at the **default** root, so the module is
dotted-importable, with `--agent-root .claude/agents` passed to the loop. The
candidate edits the persona (Zone A under that root); the graph module is Zone
C and unchanged, which is fine because only *changed* files must be Zone A.
Stated in the test's module docstring so nobody reads it as a preference.

**R2** (same hunt): `--agent-path` means the persona `.md` to the prompt
proposer and a Python graph module to preflight. Measured on this fixture:

```
[--] reflect node routed to  no reflect node in the graph
[OK] model calls visible     1 graph scanned, none reaches a model SDK …
```

Obligation 3 red for a graph whose reflect node is wired and runs; obligation 6
green having "scanned" a markdown file. The test asserts the output it actually
gets and pins the fix as
`test_doctor_judges_the_graph_when_agent_path_names_the_persona`
(`xfail(strict=True)`).

---

## The measurement the gate could not make: paired, live, and it falsifies M4

F-M5-3 blocks a live gate pass; `aef loop score` runs **in-process**, so it is
not blocked. Both arms live, cassettes stripped first so neither replays, the
candidate persona being exactly what the live cycle proposed:

| scenario | incumbent (live) | candidate (live) |
|---|---|---|
| `accela-clearwater` | 0.0000 | 0.0000 |
| `accela-pinellas` | 0.0000 | 0.0000 |
| **mean (n=2)** | **0.0000** | **0.0000** |

```
model calls: 0 cassette hit(s), 2 miss(es), on_miss=live — LIVE
```

**The lesson changed nothing**, and the reason is legible in the bullet:

> `check failed: working_memory.prompt_agent does not contain a required
> substring the owner declared`

It never names `VERDICT:`. ADR 0174 redacts the check's value from the failure
text, and that is right — ADR 0157's own caveat was that its +0.5 came from a
bullet containing the literal `contains 'VERDICT:'`, which it called *teaching
to the test*. Remove the answer and the lesson carries no information a
`contains` check can act on.

**So ADR 0157's L4 result does not reproduce on merged main, and this is the
falsification firing rather than a regression.** M4 measured a lesson that
carried the target string; M4b removed the target string; the effect went with
it. Both increments are correct and their composition buys nothing on a
`contains` check. What a rule-based prompt lesson *can* do for a check whose
answer is withheld is an open design question, not a bug — and 0.0000 → 0.0000
is well inside S2's floor (mean 0.7639, spread 0.1666 on Opus, ADR 0156) in the
only sense that matters: there is nothing to be inside of.

---

## `CLAUDE.md`, before and after

M5's brief retires the pitch paragraph when the acceptance test passes. Both
halves pass. **Before:**

> - **If your "agents" are prompt files rather than Python** — Claude Code
>   subagents, `.md` personas — there is no call site to convert. The runtime
>   attaches at the model layer instead: `model_provider.impl: claude_code`
>   (the default) runs each node's model call as one headless `claude -p`
>   under the harness's own login — no API key anywhere — and `codex` does the
>   same through `codex exec` (ADR 0112). A persona file is a system prompt to
>   that call. The previous version of this bullet said the runtime "has
>   nothing to attach to" here; that was true until the harness provider
>   existed and is not now.

**After** (commit `82c30df`, which touches nothing else):

> - **If your "agents" are prompt files rather than Python** — Claude Code
>   subagents, `.md` personas — this is the ordinary case, not the exception:
>   every eligible repo in the 2026-09-04 survey had **zero** SDK call sites.
>   `aef migrate` discovers `.claude/agents/**/*.md` recursively and writes
>   **one graph per persona**, `prompt_agent -> reflect -> consolidate -> END`,
>   with the persona read at execution time and sent as the *system* message
>   of one completion (ADR 0152). Skills are found, counted and deliberately
>   not migrated, with the reason printed. Under `claude_code`, `codex`,
>   `grok` and `anthropic` the persona's own `tools:` frontmatter is parsed,
>   reported and never obeyed — but **containment is the provider's answer,
>   not migrate's**: only `claude_code` sends `--tools "" --max-turns 1
>   --safe-mode`; `codex` and a `command:` template with no `{system}` slot
>   put the persona in the *user* turn; and for `impl: command` the
>   `isolation:` list is **the owner's assertion, recorded as one, never
>   verified against the binary** (ADR 0169). Every run writes what it
>   actually got to `working_memory["prompt_agent__containment"]`.
>   **Zone A stays `agents/` by default**, which makes the generated graph
>   agent-writable and the persona Zone C — so the loop may improve the
>   wrapper and never the prompt. `aef migrate --agent-root .claude/agents`
>   widens it, opt-in per repo, and the report says in words what that adds to
>   the blast radius: a candidate may then rewrite any persona your harness
>   loads. Pass the same `--agent-root` to every `aef loop` command.
>   With that root, `--proposer rule_based_prompt` appends one consolidated
>   lesson as a bullet under `## Lessons (aef)` — computed from records, no
>   model call, provenance in the bullet (ADR 0157) — and the gates judge it
>   with a prose control cohort (ADR 0170). **A prompt candidate is scored
>   live or not at all:** a changed prompt is a changed cassette key, so
>   replay scores it 0 and that is an artifact, not a verdict; the bar is
>   S2's measured noise floor (mean 0.7639, spread 0.1666 on Opus, ADR 0156).
>   `tests/cli/test_prompt_repo_acceptance.py` runs the whole sequence —
>   `adopt -> migrate -> bootstrap --memory -> bless -> doctor -> cycle` — and
>   ADR 0158 records what it measured, including the two defects that stop a
>   live gate pass today.

Every claim in it comes from a command that was run in this ADR: the survey
line from `UPGRADE_LOOP.md`'s table, the discovery and wiring from `aef
migrate`'s own report on the fixture, the containment paragraph from the block
`migrate` prints and from `working_memory["prompt_agent__containment"]` in a
real run, the Zone A sentences from the two `BLAST RADIUS` blocks and from the
refusal `loop doctor` emits, the proposer and cohort from the ledger excerpts
above, and the live-or-not-at-all rule from the two rejections this test
produced.

`tests/test_prompt_surface.py` passes on the new text unchanged — no pin was
edited.

---

## What the M-thread's definition of done now reads as

M5 said: *a clone of a real prompt-file repo goes adopt → migrate → bootstrap
→ bless → cycle and a candidate that edits a `.md` agent is proposed and gated
on real evidence.* Every clause of that is now executable and executed, offline
and live. The rubric is untouched (adoption claims no point).

What it does **not** yet say, and should not be read as saying: that a prompt
candidate can be *accepted*. Two defects stand between the sequence and a live
gate pass (F-M5-2, F-M5-3), and even with them fixed, the one lesson this
proposer writes today moved nothing on the one check it was grounded in. The
sequence is proved; the learning is not.

## Erratum (2026-09-05, ADR 0181) — F-M5-2 and F-M5-3 are closed

Both HIGH findings are fixed, and their two strict xfails in
`tests/cli/test_prompt_repo_acceptance.py` are passing tests now.

**F-M5-3** was fixed as the decision this ADR asked for rather than as the
one-word patch it warned against: `gates.live_model_calls` in `aef.yaml`, off
by default, read from the base ref. With it false the worker's allowlist is
byte-for-byte what it was here and `--cassette-miss live` is refused by name;
with it true the allowlist gains `sandbox.HARNESS_LOGIN_ENV`, measured to be
`USER` alone — `LOGNAME` does **not** substitute and `HOME` is not needed.
`DEFAULT_ENV_ALLOWLIST` is unchanged.

**F-M5-2** was fixed by putting the validated `ModelProviderConfig` on the wire
whole instead of `{impl, model}`; `impl: command` now rebuilds worker-side with
its argv template and `isolation:` assertion intact.

So this ADR's sentence *"no provider serves a live cassette miss inside the
gates today"* was true when written and its "today" should be read as
2026-09-04. It is false as of ADR 0181.

**The live half's conclusion is superseded.** `G2 fail — 2 previously-passing
scenario(s) no longer pass` was an artifact of F-M5-3: 29 `claude -p`
invocations exited in ~30 ms with `Not logged in`, which is also why the whole
gate pass finished in 20 seconds. Re-run on the same pilot clone, the same
persona, the same proposer and the same flag with the opt-in on, it reaches
**`G2 pass` — 2 scenarios re-executed, every previously-passing one still
passes — and `G3 fail` on the control cohort's p95**, in 115 seconds, with 12
live cassette misses served inside the worker and drift 0.007/0.500. The
verdict is REJECT either way and the two rejections are different claims: this
one is a judgement of the prompt.

What this ADR measured *about the prompt* stands and is corroborated. Its
paired in-process `aef loop score` (0.0000 → 0.0000) and its falsification of
ADR 0157's L4 reach the same conclusion G3's cohort comparison does by another
route: the rule-based lesson, with its evidence redacted (ADR 0174), carries
nothing a `contains` check can act on. ADR 0181 fixes the apparatus, not the
learning. **F-M5-1 stands, unfixed.**

## Green bar

`pytest -q`: **2511 passed, 7 skipped, 4 xfailed** (2522 collected, from 2516
before this branch — **+6, none removed**: 1 offline acceptance test, 4 strict
xfails pinning the findings, 1 live test skipped without `AEF_LIVE_HARNESS=1`).
`mypy aef examples`: 134 files, clean. `ruff check .`: clean.
`ruff format --check aef tests examples`: 271 files, clean.
No file under `aef/` was modified.
