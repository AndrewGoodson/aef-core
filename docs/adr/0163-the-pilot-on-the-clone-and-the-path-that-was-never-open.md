# ADR 0163: The pilot on the clone, and the ingestion path that was never open

## Status

Accepted. Worker **M6** of `UPGRADE_LOOP.md` — the pilot, INGEST L8 / READY K5,
run the only safe way: on a **copy of the read-only clone** at
`<scratchpad>/pilot-marlin`, never the owner's checkout at
`/Users/raptor/marlin`, never pushed anywhere (the copy's `origin` remote was
removed before anything ran, so it cannot reach the owner's repo even by
mistake). Model: `claude-opus-5[1m]` (session default). **41 live model calls** (budget ≤ 80;
`UPGRADE_LOOP.md`'s own M6 line says ≤ 60): 1 quota preflight, 5 real
objectives through `aef run`, 5 `bootstrap` recordings, 30 cassette misses
served inside the gates' worker. Every offline reproduction in this ADR cost
nothing.

**No file under `aef/` was modified.** Three defects were found in the sequence
this increment exists to run; all three are reproduced here and reported rather
than fixed, per this worker's brief, and the first two are pinned as one strict
xfail in `tests/cli/test_prompt_repo_acceptance.py`.

The rubric consequence is S7's, in ADR 0164. The one-sentence version: the
falsification fired, dimension 7 does not move, and the reason is the finding.

---

## What M6 asked for, and what happened to each clause

> Full sequence; `aef run --record-runs` on five real objectives drawn from
> marlin's own `AGENTS.md`; `aef loop harvest` (redaction on); one cycle; read
> what the gates said.

| clause | outcome |
|---|---|
| `adopt` re-run, idempotent | **done** — appended to 5 files; a second `adopt` left all five byte-identical |
| `migrate` | **done** — 8 prompt-agent graphs, one per persona |
| five real objectives, `aef run --record-runs` | **done** — 3 personas, 5 live answers, containment recorded on every one |
| the redaction scan on every recorded run | **done** — counts below, with a positive control, and one honest residual |
| `aef loop harvest` | **0 promoted, 5 REJECTED.** Not a policy refusal — a defect, in two parts, reproduced offline at zero cost |
| a corpus of real evidence | **done, by `bootstrap`, not by `harvest`** — five real objectives through the real harness, and the ADR says so wherever it matters |
| `bless`, `doctor`, one `cycle --cassette-miss live` | **done** — verdict, gates and drift quoted below |
| `monitor`, `digest` | **done** — quoted below |

---

## 0. The preflight (ADR 0150's corrected argv)

The exact argv `ClaudeCodeProvider` builds, run as a subprocess, not a shape
assertion:

```
claude -p --no-session-persistence --output-format json --max-turns 1 \
  --tools '' --strict-mcp-config --mcp-config '{"mcpServers":{}}' --safe-mode \
  --model claude-opus-5 OK
```

```json
{"is_error": false,
 "result": "Ready when you are — what would you like to work on?",
 "usage": {"input_tokens": 2, "cache_creation_input_tokens": 2770,
           "output_tokens": 17, "service_tier": "standard"}}
```

**1 call.** Raw response: `docs/research/pilot-marlin/00-preflight.json`.

## 1. `adopt` into a repo that was adopted by an older `aef`, and again

The clone had already been adopted once, before ADR 0153 taught `adopt` to
append. So the re-run is the interesting case rather than a no-op:

```
$ aef adopt --dir .
detected framework: prompt_files (8 agents, 5 skills, AGENTS.md, .codex,
  .github/copilot-instructions.md, 1 cursor rule)
appended aef block to .../CLAUDE.md (your bytes outside it are unchanged)
appended aef block to .../.gitignore (your bytes outside it are unchanged)
appended aef block to .../AGENTS.md (your bytes outside it are unchanged)
appended aef block to .../.github/copilot-instructions.md (…)
appended aef block to .../.cursor/rules/aef.mdc (…)
skipped .../aef.yaml (already exists)          [and 14 more skips]
```

Insertions only, checked rather than claimed:

```
$ git diff --numstat -- AGENTS.md .gitignore
36  0  AGENTS.md
5   0  .gitignore
```

**Idempotence, byte-verified** (ADR 0153/0172): sha256 of all five appended-to
files taken, `adopt` run a second time, `shasum -c` re-run:

```
AGENTS.md: OK
CLAUDE.md: OK
.gitignore: OK
.github/copilot-instructions.md: OK
.cursor/rules/aef.mdc: OK
```

and `--numstat` still `36 0` / `5 0` — the second run replaced each block with
identical bytes rather than appending a second one.

Full output: `docs/research/pilot-marlin/01-adopt.txt`.

## 2. `migrate` at the default root — 8 graphs

```
found 8 prompt agent(s) under .claude/agents
  AGENT  marlin-accela  (.claude/agents/accela-agent.md)
          -> agents/migrated/marlin_accela/graph.py
          graph_id='marlin-accela', wired prompt_agent -> reflect -> consolidate -> END
  … marlin-azure, marlin-bug-hunter, marlin-implementer, marlin-orchestrator,
    marlin-reviewer, marlin-security, marlin-source
found 5 skill(s) and did NOT migrate any of them
```

The default root is deliberate and is ADR 0158's R1 workaround, unchanged: the
generated module must be dotted-importable, so `migrate` runs at `agents/` and
`--agent-root .claude/agents` is passed to every `aef loop` command instead.
The persona is then Zone A for the loop and the graph module is Zone C — which
is fine, because only *changed* files must be Zone A.

Full output: `docs/research/pilot-marlin/02-migrate.txt`.

## 3. `aef.yaml` — and the owner's opt-in, stated as an opt-in

```yaml
model_provider:
  impl: claude_code
  model: ""            # empty = the session default the harness itself picks
gates:
  live_model_calls: true
```

`model: ""` is not a placeholder: `harness_provider` builds `--model` only when
`request.model or self._default_model` is truthy, so an empty string omits the
flag and the CLI answers on its session default. Every recorded run's
provenance says which model that was: `claude-opus-5[1m]`.

`gates.live_model_calls: true` is **the owner's opt-in and nothing less** (ADR
0181). What it permits, in the owner's own terms: the gates' sandbox worker —
the one process in this repo that executes code an agent wrote — gains
`sandbox.HARNESS_LOGIN_ENV` (measured to be `USER` alone), so a candidate's
model calls run under this machine's harness login and **spend this operator's
quota**. Off by default everywhere else, read from the base ref so a candidate
cannot grant it to itself, and recorded on every `gated` ledger event. Turning
it on is why the cycle below could score a changed prompt at all; without it
`--cassette-miss live` is refused by name.

## 4. Five real objectives, answered by the real harness

Drawn from marlin's own `AGENTS.md` boundary rules and from the persona bodies
— the questions those agents exist to answer — across **three** personas
(`marlin-accela` ×2, `marlin-source` ×2, `marlin-reviewer` ×1). `--tools ""`
is the provider's, so the agents produced text and touched nothing; the
containment block each run recorded says so:

```
{'provider': 'claude_code',
 'isolation': ['no_mcp', 'no_project_context', 'no_tools', 'single_turn', 'system_role'],
 'persona_role': 'system'}
```

Objective and first answer line, both after redaction (all five had **0**
substitutions, so these are also the raw first lines):

| | objective | first line of the answer |
|---|---|---|
| O1 | *The City of Clearwater has just provisioned Marlin-owned Accela app credentials in Key Vault. Should the Clearwater Accela connector's enabled flag be set to true on the next ingestion run?* | `**Short answer: No.** Credentials are gate #1 of two. `enabled` stays `false`.` |
| O2 | *For agency TAMPA in the PROD environment, which OAuth2 grant type and which request parameters does a server-to-server Accela v4 token request need, and where do the App ID and App Secret come from?* | `## Answer (advisory — no calls made, no credentials touched)` |
| O3 | *An ArcGIS permit layer returned a page of 2000 features with no exceededTransferLimit flag. Fetched 2000, lake 2000, published 2000. Is this run reconciled, and may scheduled ingestion be enabled?* | `## Answer: No, and no.` |
| O4 | *A Socrata permit dataset exposes issue_date, last_updated and :updated_at. Which field is the ingestion watermark, what grace_days does it need, and which tests must pass before the schedule is enabled?* | `## Answer` |
| O5 | *A handoff-v1 packet names marlin-implementer as both sender and receiver, carries three evidence entries whose git_tree_sha values disagree, and sets explicit_authorization to false. What review status applies and may it recommend ship?* | `## Review result` |

**5 calls.** 453–949 words each. Full artefact, with lengths and run ids:
`docs/research/pilot-marlin/03-objectives-and-answers.txt`.

These are the "live traffic" the trust case asks for in the only sense this
pilot can supply: real prompts, the real harness, a repo nobody wrote to pass.
They are **not** a third party's traffic, and the last section says what that
would take.

## 5. The redaction scan, on every recorded run — and its control

ADR 0119's `RedactionPolicy`, the shipped default, over all five runs. The
counts, which are the thing M6 asks to be quoted:

```
patterns: email, api_key, bearer, aws_key, opaque_secret
working_memory keys dropped outright: ['api_key', 'token', 'secret', 'password']

5 recorded run(s)
  INPUT scan   0 substitution(s) on every run; 0 working-memory keys dropped
  OUTPUT scan  clean on every run (0 labels matched the scenario harvest would write)
  answers      0 substitution(s) inside any of the five answers
totals: {"input_subs": 0, "output_hits": 0, "wm_dropped": 0}
```

**Nothing was redacted, nothing was refused, and a zero is exactly the number a
scanner that never ran would also produce** — so the control ADR 0119 demands
was run rather than assumed. The same policy, over the same real run, with one
credential-shaped token planted in the objective at a time:

```
email           substitutions=1  -> ... (contact [REDACTED:email])
api_key         substitutions=1  -> ... (contact [REDACTED:api_key])
bearer          substitutions=1  -> ... (contact [REDACTED:bearer])
aws_key         substitutions=1  -> ... (contact [REDACTED:aws_key])
opaque_secret   substitutions=1  -> ... (contact [REDACTED:opaque_secret])

secret-shaped working-memory keys:
  before ['api_key', 'keep_me', 'token']  ->  after ['keep_me']  (count=2)
```

5 of 5 shapes caught, 2 of 3 keys dropped. The scan scans.

**The residual, named because a redaction claim with no residual is a claim
nobody checked.** Marlin's boundary rule is written around one identifier — the
subscription UUID `7e16b0bb-…-839cf1b96755`, quoted in its own `AGENTS.md` — and
the default pattern list does **not** match it:

```
marlin's own subscription UUID: substitutions=0
-> Marlin subscription 7e16b0bb-b75a-4a16-9765-839cf1b96755; resource group rg-marlin-dev
```

The reason is a correction rather than an oversight: ADR 0126 removed `-` from
`opaque_secret`'s character class because a hyphenated plain-English objective
was being redacted into a placeholder. A UUID is hyphenated, so it survives. An
adopter whose secrets are UUID-shaped must extend the list; `RedactionPolicy`
takes the patterns as data precisely so they can. This is a real gap for *this*
repo and it is the first thing its owner should change.

Artefacts: `docs/research/pilot-marlin/05-redaction-scan.txt`,
`06-redaction-control.txt`, and the two scripts beside them. **The scan's output
is what is committed; no raw recorded run is.**

> **Erratum, 2026-09-05 (ADR 0197).** The residual above is **closed in the
> code and not in the committed `.txt`**. `DEFAULT_PATTERNS` now carries a
> `uuid` shape (8-4-4-4-12 hex, every group hex-only and length-exact, so it
> cannot revive ADR 0126's hyphenated-English false positive), and the same
> control re-run today reads:
>
> ```
> marlin's own subscription UUID: substitutions=1
> ```
>
> `06-redaction-control.txt` still shows `substitutions=0`: it is the artefact
> M6 produced and is left as the record of what was true then.
> `python docs/research/pilot-marlin/scan_control.py --verify` is the version
> that runs, and `make measure` pins this line against this paragraph.
> Five more shapes landed with it — `jwt`, `github_token`, `slack_token`,
> `connection_string`, and four more AWS key prefixes — and `api_key` was
> widened, because `sk-ant-api03-<36>` matched nothing at all.

## 6. `aef loop harvest` — 0 promoted, 5 rejected, and why

```
$ aef loop harvest agents.migrated.marlin_accela.graph --runs <runs> --corpus corpus --state <state>
promoted 0 run(s) to the train split
  5 passed, not promoted: 22a5f0ec…, 491c4102…, 7d10629e…, 999d7f25…, 9c48f5c9…

$ … --include-successes
promoted 0 run(s) to the train split
  5 REJECTED, did not re-execute deterministically: 22a5f0ec…, 491c4102…,
    7d10629e…, 999d7f25…, 9c48f5c9…
```

The first line is correct behaviour: none of the five runs *failed*, and
harvest promotes failures unless asked otherwise (ADR 0060's rule — successes
inflate the pass rate the gates measure against). The second line is the
finding. **The redaction step is never reached**: the determinism re-check runs
before it, so on this repo the redaction counts above could only be produced by
running the policy directly, which is what §5 did.

### F-M6-1 (HIGH) — the recorder does not record the cassette

`aef/cli/run.py`'s `--record-runs` block constructs

```python
RecordedRun(run_id=…, graph_id=…, graph_version=…, initial_state=state,
            trace=result.trace, at=datetime.now(UTC))
```

with no `model_calls=`, so the field takes its default `()`. `RecordedRun`'s own
docstring states the consequence in advance:

> Without these a run whose graph calls a model cannot re-execute at all: the
> determinism re-check runs with no credential, the call fails, and the run is
> rejected as non-deterministic — **a correct-looking rejection for the wrong
> reason.**

Observed on every one of the five real runs (`model_calls 0` in
`05-redaction-scan.txt`), and reproduced offline for free against a stub
`command` provider:

```
== 1. what `aef run --record-runs` wrote
   45624a03-….json: model_calls=[]
== re-execution
   ModelProviderError: cassette miss (key 368925550fdc, model '', 2 message(s)…):
     no recorded completion for this request and on_miss='fail'
```

`aef loop record` and `aef loop bootstrap` do not have this defect: both go
through `recorder.py`, which wraps the provider in a `CassetteProvider` and
stores `recording.recorded`. `aef run --record-runs` is the one recording path
that does not, and it is the only one the harvest pipeline is documented to be
fed from (`--runs`, in `harvest`, in `cycle`, and in the generated cron).

### F-M6-2 (HIGH) — the determinism re-check cannot reproduce a containment block

Fixing F-M6-1 is not enough, which is why this is a second finding rather than
a detail of the first. With the cassette populated by hand, the same run is
still rejected, and the divergence is one field:

```
LEN  .working_memory.prompt_agent__containment.isolation   3 -> 0
DIFF .working_memory.prompt_agent__containment.persona_role
   recorded:    'system'
   re-executed: 'unknown'
```

`harvest._reexecution_services` builds `CassetteProvider(None, scenario.model_calls,
on_miss="fail")` — **no inner provider**, on purpose, because "a harvest that
reaches the network to decide whether a run is deterministic has already lost
the property it is checking". `CassetteProvider.isolation` forwards the inner
provider's declaration and reports nothing when there is none, so the
`prompt_agent` node ADR 0169 added writes an empty isolation set and
`persona_role: unknown` on re-execution. `_reexecutes_identically` compares the
encoded trace **byte for byte**, so the run is rejected.

Two mechanisms that are each right: ADR 0169 records what containment a run
actually got, into the state, so a claim is never inherited unverified; ADR 0126
pins the cassette into the re-check so a model-calling run is not rejected for
having no credential. Their join is a per-run field whose value is a property of
the *provider object* and which the re-check has no provider to derive. That is
a seam, in the sense `.claude/agents/seam-hunter.md` means.

### Both blockers isolated to one variable each

`docs/research/pilot-marlin/repro_two_blockers.py`, offline, zero live calls,
nothing under `aef/` edited — arm 2 monkeypatches `_reexecution_services` **in
that process only**, to price the missing piece:

```
== arm 0 — as shipped (`aef run --record-runs`)
   promoted 0 run(s); 1 REJECTED, did not re-execute deterministically
== arm 1 — + the cassette the recorder never wrote
   promoted 0 run(s); 1 REJECTED, did not re-execute deterministically
== arm 2 — + the provider the re-check never has (patched in THIS process)
   promoted 1 run(s) to the train split
   corpus now holds: ['manifest.json', 'train/45624a03-….json']
```

### What that means, stated plainly

**No run of any `aef migrate`-generated prompt-agent graph has ever been
harvestable, on any repo, by any invocation.** ADR 0151's J0 scored dimension 7
at 4/10 on the observation that *"no live signal has ever entered harvest; the
cron's `--runs` is populated by no step"*. This pilot supplies the mechanism
behind that observation: the step exists, it is documented, an owner can run it,
and its output is refused — with a message that names flakiness, which is the
one explanation the evidence rules out.

A third observation, reported without a reproduction of harm: `harvest()`
iterates `load_runs(runs_dir)` with **no filter on `run.graph_id`**, and stamps
each promoted scenario with the run's own `graph_id` while having re-executed it
against the graph named on the command line. Here it is masked — a run from
another persona misses the cassette and is rejected — but the masking is
F-M6-1's doing, and it would stop masking the moment F-M6-1 is fixed.

## 7. Which path populated the corpus, and the owner checks

`harvest` admitted nothing, so **`bootstrap` populated the corpus** — and the
distinction matters exactly as much as M6 says it does, so it is stated here
rather than smoothed. What is the same either way: the objectives are real
questions from marlin's own rules, the persona is marlin's own, the harness is
the real one, and the answers were produced live. What is different: a
bootstrapped scenario is a run the *system* initiated from an inputs file, and a
harvested one is a run that happened for its own reasons and was picked up
afterwards. The second is what the trust case's criterion 1 means by live
traffic; only the first was reachable tonight.

Five inputs, one uniform owner check applied to all of them — **the same rule,
written once, not tuned per input**:

> `working_memory.prompt_agent` must contain `developer.accela.com`. An answer
> about Accela credentials must say *where* Marlin-owned credentials come from,
> by host: the persona's own rule is that the Developer Portal issues App ID and
> App Secret and the ACA citizen portal does not, and "obtain credentials"
> without the host is the exact confusion that rule exists to prevent.

That is a sentence a reader could dispute, and the obvious dispute is fair: on
O1 the question was only whether to flip a flag, so naming the credential source
is arguably out of scope. It is the owner's claim, and the owner is the one who
gets to be wrong about it. **Disclosure**: the five recorded answers were
inspected before the check was written, to know whether a failure was reachable
at all; the check itself was then written from the persona's rule and applied
unchanged to every input.

```
$ aef loop bootstrap agents.migrated.marlin_accela.graph --corpus corpus \
    --inputs inputs.json --memory <state>/memory.jsonl --config aef.yaml --state <state>
recorded 3 scenario(s) in the train split
  WRONG   accela-clearwater
  passed  accela-tampa-token
  passed  accela-pinellas
1 of 3 recorded run(s) FAILED: 0 raised or ended with a failed plan, 1 failed an
  owner check — the task metric, which fails without an error (ADR 0113).
  recording spent 3 live model call(s). …
  4 memory record(s) written to the durable store …
  1 of them is/are a check-derived FAILURE record … (ADR 0174). A signature
  recurring in two distinct runs becomes a lesson (ADR 0110).

$ … --inputs inputs2.json …
recorded 2 scenario(s) in the train split
  passed  accela-inspections
  WRONG   accela-sarasota-no-api
1 of 2 recorded run(s) FAILED: … 1 failed an owner check …
  1 of them is/are a check-derived FAILURE record …
```

**5 live calls.** Two of five real questions failed the owner's one rule, in two
distinct runs, under one signature — because ADR 0174 keys a check by
`check:<path>:<op>` **without its value**, which is what makes ADR 0110's
two-run threshold reachable across scenarios that fail the same field for
different reasons.

The durable store afterwards, in full:

```
success | 9c48f5c9…  (O1, from `aef run --memory`)   … 5 of these, the real runs
success | accela-clearwater
failure | accela-clearwater        failed_checks: ['check:working_memory.prompt_agent:contains']
success | accela-tampa-token
success | accela-pinellas
success | accela-inspections
success | accela-sarasota-no-api
failure | accela-sarasota-no-api   failed_checks: ['check:working_memory.prompt_agent:contains']
```

The five `aef run` records are in there too, as successes — so the real runs did
reach memory even though they could not reach the corpus. They contribute
nothing to a proposal, because a proposal is grounded in failure.

## 8. `bless` and `doctor`

```
$ aef loop bless --agent-root .claude/agents --agent-path .claude/agents/accela-agent.md …
blessed .claude/agents/accela-agent.md as baseline v1 for graph 'marlin-accela'
  G5 now has a reference point to measure drift against.

$ aef loop doctor --agent-root .claude/agents --agent-path .claude/agents/accela-agent.md --corpus corpus …
Loop readiness — 6 things you must supply
  [--] corpus + tripwire       5 scenario(s), 0 tripwire(s)
  [OK] reflect node routed to  agents/migrated/marlin_accela/graph.py:
                               make_prompt_agent_node(route='reflect') builds a node that routes to it
  [--] observations            0 recorded run(s) at <state>/observations.jsonl
  [--] halt channel            none — a halt would tell nobody
  [OK] blessed baseline        1 archived version(s) of '.claude/agents'
  [OK] model calls visible     2 graphs scanned, none reaches a model SDK the harness cannot see
```

Three met, three not, and the three unmet are the owner's to supply: a tripwire
scenario, a halt webhook, and production observations. Obligation 2 resolved the
**graph** while `--agent-path` named the **persona**, which is ADR 0178's R2
behaving as fixed rather than as ADR 0158 found it.

## 9. One cycle, live

ADR 0181's form, on the real corpus, with the opt-in on:

```
$ aef loop cycle --repo . --state <state> --workdir <wd> --corpus corpus \
    --runs <runs> --proposer rule_based_prompt --agent-root .claude/agents \
    --agent-path .claude/agents/accela-agent.md \
    --entrypoint agents.migrated.marlin_accela.graph:build_graph \
    --memory <state>/memory.jsonl --config aef.yaml --cassette-miss live \
    --build-command "python -c pass"

  --graph-id not given; derived 'marlin-accela' from the 5 scenario(s) in corpus,
    which record one graph
  preflight: 3 of 6 obligation(s) unmet (corpus + tripwire, observations, halt
    channel). ADVISORY — this command does not refuse on them …
  ledger verified: 1 entr(ies)
  proposed cycle-20260905T075043-prompt on local branch
    loop/cycle-20260905T075043-prompt (never pushed; proposer=rule_based_prompt)
  gated: reject — G3 rejected it: 1 previously-passing scenario(s) now score
    below 0.5 (zero tolerance, regardless of the aggregate)
```

The diff, in full — one bullet, four lines, one file:

```diff
--- a/.claude/agents/accela-agent.md
+++ b/.claude/agents/accela-agent.md
@@ -106,3 +106,7 @@
+
+## Lessons (aef)
+
+- <!-- aef sig=failure:check:working_memory.prompt_agent:contains runs=2 -->
+  1 error(s) recorded; 0/0 tool call(s) failed. errors[0]: check failed:
+  working_memory.prompt_agent does not contain a required substring the owner
+  declared; observed 603 words, 4098 chars
```

Note what is **not** in it: any of the model's own text. ADR 0180's finding 2
shipped between ADR 0158 and this pilot, and the excerpt ADR 0158 quotes
(`… 2836 chars: '**No. The Accela connector…'`) is gone. The counts the harness
computed survive; the quotation the harness merely copied does not.

The `gated` ledger entry, in full (`docs/research/pilot-marlin/13-ledger.json`):

```
live_model_calls: True
proposer: rule_based_prompt
evidence: 7 corpus pass(es) (35 scenario execution(s)): 1 candidate +
          1 incumbent + 5 random control(s); 5/5 gated scenario(s) recorded
          from graph 'marlin-accela'
G0 pass  1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically scanned,
         no violations; 1 NOT statically scanned (not Python …)
G1 pass  1 build command(s) succeeded against the merged workspace
G4 pass  no owner-only safety metadata declared by the candidate
G5 pass  0/3 accepted in the last 7d; drift 0.007/0.500 from the blessed baseline
G2 pass  5 scenario(s) re-executed; every previously-passing one still passes.
         0 changed routing (reported, not rejected).
G3 fail  1 previously-passing scenario(s) now score below 0.5 (zero tolerance,
         regardless of the aggregate)
grounded_in:
  checkfail-3073e89f… (memory): failure:check:working_memory.prompt_agent:contains recurred
  checkfail-7b6e5115… (memory): failure:check:working_memory.prompt_agent:contains recurred
kinds: ['blessed', 'proposed', 'gated', 'rejected']
```

**Verdict: REJECT, by G3. Drift consumed: 0.007 of 0.500. 35 scenario
executions, 30 of them live cassette misses served inside the gates' worker.**
The count follows from the cohort: the incumbent's five hit the cassette because
its persona is byte-identical to the recording's, and the candidate's five plus
the five controls' twenty-five are all changed prose and therefore changed
cassette keys.

**Read against ADR 0181, which is the same repo, the same persona and the same
proposer, this is a third distinct rejection** and the strongest of the three:

| | ADR 0158 | ADR 0181 | here |
|---|---|---|---|
| G2 | fail — 2 no longer pass | pass — 2 re-executed | **pass — 5 re-executed** |
| G3 | never ran | fail — does not beat the cohort's p95 | **fail — one scenario's score fell below 0.5** |
| what the rejection claims | the worker could not log in | the lesson did not help | **the lesson HURT a scenario that was passing** |
| grounded in | synthesised failure memory | 2 bootstrap runs | **2 real marlin questions about Accela credentials** |

The third row is the one worth pausing on. ADR 0181's G3 said *null result*;
this one says *regression*, on the task metric, on a scenario the incumbent
passed. That is the shape ADR 0162 measured and ADR 0180 partly fixed — a
lesson bullet making the very behaviour it describes worse — reproduced here on
a repo neither of them touched, with the output excerpt already removed. So the
excerpt was not the whole mechanism.

**G2 passed while G3 failed on the same run**, which is exactly ADR 0162's "two
conflated signals" separating in the wild: G2 asks whether the outcome
classification changed and G3 asks what the score is, and a scenario can keep
its `passed` label while its check fraction collapses. The gate that caught the
harm is the one reading the number.

One thing the ledger does **not** say: *which* scenario regressed. G3's reason
carries the count and not the id, so an owner reading this in the morning knows
a scenario broke and must re-score to learn which. Reported, not fixed.

## 10. `monitor` and `digest` — what the owner reads the next morning

```
$ aef loop monitor …
checked 0 merged change(s)
  cycles run: 1 (last 0.0 day(s) ago)
  last PROPOSED: 0.0 day(s) ago
  last KEPT/MERGED: never
```

```
$ aef loop digest … --runs <runs>
# Self-rewiring digest, 2026-08-29 to 2026-09-05
- Proposed: 1
- Merged: 0 (acceptance rate 0%)
- Rejected: 1
- Escalated to you: 0
- Security events: 0
- Halts: 0
- Scenarios added to the corpus: 0
- Drift from the blessed baseline: 0.000
- Production runs recorded: 5
- Halt channel configured: NO

**No halt channel is configured.** …
```

**`Production runs recorded: 5` and `Scenarios added to the corpus: 0`, side by
side, with no line drawn between them.** That pair is this whole ADR in the one
document an owner is meant to read weekly, and the digest has nothing to say
about it. Its warning about recording fires only when the count is *zero*:

```
$ aef loop digest …            # --runs omitted, which is its default
- Production runs recorded: 0
**No production runs were recorded**, so the corpus cannot grow and the gates
keep measuring what the agent used to do. Pass `--record-runs` from your
deployment.
```

— advice this pilot had already followed five times. The zero is the flag's
absence, not the deployment's; and when the flag *is* given and the number is 5,
the report says nothing at all about the corpus not growing. Reported, not
fixed.

### F-M6-3 (MEDIUM) — `cycle --runs` is a no-op without `--module`

Found by noticing the cycle above printed no harvest line. `cmd_cycle` does
`graph = load_graph_reference(args.module) if args.module else None`, and
`harness/loop.py::cycle` runs its harvest leg only `if runs_dir is not None and
corpus_root is not None and graph is not None`. With `--entrypoint` and no
`--module` — the spelling a widened-root prompt repo uses, and the spelling this
pilot and ADR 0181 both used — `--runs` is accepted, its path validated, and
nothing happens.

Reproduced on two invocations differing in one flag, both `--no-memory` so
neither costs a call (`docs/research/pilot-marlin/14-cycle-runs-noop.txt`):

```
arm A  --entrypoint only:  ledger verified: 4 entr(ies)
                           no memory store configured: …        <- no harvest line
arm B  + --module:         ledger verified: 4 entr(ies)
                           promoted 0 run(s) to the train split
                             5 passed, not promoted: 22a5f0ec…, …
                           no memory store configured: …
```

This is not why harvest promoted nothing — §6 shows it promotes nothing when it
*does* run — but it is a third way the ingestion path fails quietly, and it is
ADR 0176's "two spellings of which graph" in a fourth place.

---

## What still requires a person

1. **A real checkout.** This ran on a copy of a read-only clone with its remote
   removed. Running it where marlin's own agents actually run means letting the
   loop write branches in the owner's repository, and that is the owner's
   decision, not a worker's.
2. **A third party.** Marlin is the same owner's repo. Every objective in this
   pilot was written by the same process that read the personas — so "a repo
   nobody wrote to pass" is true of the *repo* and not of the *objectives*. The
   trust case's criterion 6 says "real tenants", and a tenant is someone else.
   That remains unclaimed, with the reason, in ADR 0164.
3. **The two blockers.** F-M6-1 and F-M6-2 are a fix worker's, not this
   worker's. Until both are closed, `--runs` is a flag that costs an owner
   nothing and buys them nothing, on every adopted repo.
4. **The redaction list for this repo.** The default patterns do not match
   marlin's subscription UUID. That is an owner extension, and the pilot names
   the exact string it would have to cover.

## What is pinned, and what is only written down

`tests/cli/test_prompt_repo_acceptance.py` gains two tests and **no file under
`aef/` changes**:

- `test_a_recorded_production_run_can_be_harvested_into_the_corpus` —
  `xfail(strict=True)`, offline against the same synthetic repo and the same
  `command` stub the offline half already uses: `adopt` → `migrate` → `aef run
  --record-runs` → `aef loop harvest --include-successes`, asserting
  `promoted 1 run(s)`. It fails loudly the day **both** F-M6-1 and F-M6-2 are
  closed, and stays xfailing if only one is — which is the right behaviour,
  because the three-arm isolation above shows one fix alone changes nothing.
- `test_the_recorder_pins_the_cassette_the_determinism_check_needs` — a passing
  description of the one-line cause, so `model_calls=` in
  `run_graph_module` is greppable from the suite rather than only from an ADR.

F-M6-3 is written down and **not** pinned: a test asserting today's silence
would be a test asserting a defect.

## Green bar

```
pytest -q                                2721 passed, 7 skipped, 2 xfailed
                                         (2730 collected, from 2728 before this
                                          branch — +2, none removed: 1 strict
                                          xfail and 1 passing description)
mypy aef examples                        Success: no issues found in 135 source files
ruff check .                             All checks passed!
ruff format --check aef tests examples   280 files already formatted
```

Two things about that run, both recorded because both look like regressions and
neither is:

- **Run the suite with `PATH=<repo>/.venv/bin:$PATH`.** Without it 30 tests fail
  on `[Errno 2] No such file or directory: 'python'`: `run_sandboxed` scrubs
  `PATH` to its allowlist and the tests' build commands spell the interpreter
  `python`. That is the harness working.
- `tests/harness/test_container_sandbox.py::test_a_timed_out_container_is_actually_dead`
  failed once on a loaded box, mid-pilot, and passed in isolation (25 passed) and
  on the clean re-run above. A timing assertion about killing a container, under
  contention. Named rather than left in the scrollback.


## Erratum (2026-09-05, ADR 0190)

**F-M6-1, F-M6-2 and F-M6-3: all CLOSED** by fix worker L2, each reproduced
independently before being fixed and mutation-checked after.

- §6's sentence *"No run of any `aef migrate`-generated prompt-agent graph has
  ever been harvestable, on any repo, by any invocation"* was true when written
  and is false now. `test_a_recorded_production_run_can_be_harvested_into_the_corpus`
  — the strict xfail this ADR left behind — is a passing test asserting the
  opposite, and `test_the_recorder_pins_the_cassette_the_determinism_check_needs`
  is now `test_every_recording_path_goes_through_one_recorder`, asserting the fix
  rather than describing the defect.
- §6's third observation (harvest does not filter `--runs` by `graph_id`) is
  fixed and reported in the outcome's own lines. Its prediction was right: the
  masking was F-M6-1's doing and would have lifted the moment F-M6-1 was fixed.
- §10's *"`Production runs recorded: 5` and `Scenarios added to the corpus: 0`,
  side by side, with no line drawn between them"* — the line is drawn.
- "What still requires a person" item **3 is discharged**. Items 1 (a real
  checkout), 2 (a third party) and 4 (marlin's UUID-shaped secrets, which the
  default pattern list does not match) stand untouched.

**The five runs of §4, through the fixed leg: 5 of 5 promoted** — re-recorded
through the fixed recorder from *their own* recorded declaration (the five-element
`claude_code` set in each run's containment block) and *their own* recorded
answers (the text in each run's trace), so nothing was re-requested and no live
call was spent. The honest other half: the five run **files** in
`<scratchpad>/w/m6/runs` still reject, five for five, because they were written
by the old recorder and carry no cassette and no declaration. A fix does not
retro-repair an artefact; putting these five into a corpus means re-running `aef
run --record-runs`, which costs live calls and is M-series work. So *"re-run this
pilot today and it harvests"* remains an inference — from a mechanism now
measured on this provider's real declaration rather than on a stub's.
