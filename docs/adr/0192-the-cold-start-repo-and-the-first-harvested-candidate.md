# ADR 0192: The cold-start repo, and the first candidate this program has ever grounded in harvested evidence

## Status

Accepted. Worker **N7** of `ABOVE_95_LOOP.md` — the pilot on **`peptideindex`**,
the first repo tested in this program with **no agentic surface at all** (no
`.claude/agents/`, no `CLAUDE.md`, no `AGENTS.md`, no `.codex/`, 0 SDK call
sites) and the first whose default branch is not `main`.

Model: `claude-opus-5[1m]` (session default). **40 live model calls** (budget
≤ 60): 1 quota preflight, 5 real objectives through `aef run --record-runs`, 4
re-recordings forced by the defect §5 reports, and 30 cassette misses served
inside the gates' worker. Every reproduction in this ADR cost nothing.

Steps 1–6 ran on a **clone** at `<scratch>/peptide` whose `origin` was removed
before anything ran, so it cannot reach the owner's repository even by mistake.
Step 7 touched `/Users/raptor/peptideindex` and only as §7 describes: one local
branch, one commit, **never pushed**, `master` byte-for-byte what it was.

**No file under `aef/` was modified.** Three defects were found in the sequence
this increment exists to run and a fourth at commit time, in a change that
landed on the trunk while this pilot was running; all four are reproduced here
and reported rather than fixed, per this worker's brief.

The rubric consequence is one row, dimension 7 at **3 → 5**, and §9 states what
the last five points would take.

---

## What N7 asked for, and what happened to each clause

| clause | outcome |
|---|---|
| what a cold-start repo gets from `adopt` + `migrate` | **done** — 17 files, all NEW, nothing overwritten; a second `adopt` left all 17 byte-identical; `migrate` found 0 call sites and 0 prompt agents and wrote a `build_graph()` that **raises** |
| L1's fix on a real `master` repo | **done** — three derivations, including one on the owner's own checkout while HEAD was on another branch; `--base main` is `EXIT_ERROR` |
| one persona, as the owner's proxy, in writing | **done** — `price-freshness-reviewer`, justified in §3 in a sentence a reader can dispute |
| five objectives, live, `--record-runs` | **done** — 5 real questions from this repo's own data and its own HEAD commit, answered by `claude_code`, containment recorded on every one |
| `harvest` with redaction on, and its control | **done** — and it found **F-N7-1**: 1 of 5 admitted, 4 rejected, isolated to one variable |
| owner checks so ≥ 1 fails | **done** — 3 rules, values computed not typed; 2 of 5 scenarios fail |
| one cycle, `--cassette-miss live` | **done** — REJECT by G3; ledger, drift and gates quoted |
| **the cycle grounded in harvested evidence** | **done, and this is the first time in the program** — both cited records' runs are corpus scenarios with `source: harvest`; the corpus is `{"harvest": 5}`, bootstrap 0, record 0 |
| `monitor`, `digest` | **done** — and the digest found **F-N7-2** |
| the real repo, on a branch | **done** — 1 commit, 16 files, 2691 insertions, 0 deletions, no push |
| the artefacts, re-scanned at commit time | **F-N7-4** — ADR 0197's new `uuid` pattern (added to close the residual §5 names) turns this pilot's own harvest from **5 promoted** to **0 promoted, 5 REJECTED, a secret survived redaction**, because a run's own id is a UUID |

---

## 0. The preflight (ADR 0150's argv)

```
claude -p --no-session-persistence --output-format json --max-turns 1 \
  --tools "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --safe-mode \
  "Reply with the single word OK"
```

```json
{"is_error": false, "result": "OK", "num_turns": 1,
 "modelUsage": {"claude-opus-5[1m]": {"inputTokens": 2, "outputTokens": 4,
   "cacheCreationInputTokens": 2792, "canonicalModel": "claude-opus-5"}}}
```

**1 call.** Raw response: `docs/research/pilot-peptide/00-preflight.json` (the
session identifier is scrubbed; nothing else is).

## 1. What an agentless repo actually gets

### `aef adopt --dir .`

```
detected framework: none
wrote <repo>/CLAUDE.md
wrote <repo>/aef.yaml
wrote <repo>/aef_adapter.py
wrote <repo>/AGENT_INTEGRATION.md
wrote <repo>/AUTONOMY.md
wrote <repo>/AGENTS.md
wrote <repo>/.github/copilot-instructions.md
wrote <repo>/.cursor/rules/aef.mdc
wrote <repo>/AEF_MIGRATION_CHECKLIST.md
wrote <repo>/LOOP.md
wrote <repo>/FIRST_DAY.md
wrote <repo>/agents/README.md
wrote <repo>/corpus/README.md
wrote <repo>/.github/workflows/loop-gate.yml
wrote <repo>/.github/workflows/loop-monitor.yml
wrote <repo>/.claude/skills/new-model-check/SKILL.md
skipped <repo>/.gitignore (already exists)
```

**Sixteen files written, one skipped, nothing appended and nothing modified.**
That is the cold-start case's whole difference from marlin's (ADR 0163 §1,
where `adopt` appended to five existing files): a repo with no agentic surface
has nothing for `adopt` to append *to*, so `git status` afterwards is 14
untracked paths and **zero modified files**.

The one skip is correct behaviour and was checked rather than assumed:
`gitignore_covers_bytecode` reads rules and not comments, this repo's
`.gitignore` line 2 is `__pycache__/`, and ADR 0142's whole point is that
nagging an adopter to add a pattern equivalent to one they have is how
generated advice stops being read.

**Idempotence, byte-verified** (ADR 0153/0172): sha256 of all 17 adopt-written
files taken, `adopt` run a second time, `shasum -c` re-run —

```
skipped <repo>/CLAUDE.md (already carries the current aef block)
skipped <repo>/aef.yaml (already exists)                    [and 15 more skips]
```
```
./AEF_MIGRATION_CHECKLIST.md: OK   ./AGENTS.md: OK   ./AGENT_INTEGRATION.md: OK
./AUTONOMY.md: OK   ./CLAUDE.md: OK   ./FIRST_DAY.md: OK   ./LOOP.md: OK
./aef.yaml: OK   ./aef_adapter.py: OK   ./agents/README.md: OK
./corpus/README.md: OK   ./.claude/skills/new-model-check/SKILL.md: OK
./.cursor/rules/aef.mdc: OK   ./.github/copilot-instructions.md: OK
./.github/workflows/loop-gate.yml: OK   ./.github/workflows/loop-monitor.yml: OK
```

`01-adopt.txt`, `01b-adopt-again.txt`, `01b-shasum-c.txt`.

### `aef migrate --dir .`

```
scanned 21 Python file(s)
found 0 call site(s): 0 wrapped, 0 skipped

wrote <repo>/agents/migrated/graph.py
  Zone A (agents/**) — agent-writable, the only tree the self-rewiring loop may
  propose changes to

found 0 prompt agent(s) under .claude/agents
  none — this repo's agents are not markdown personas in that directory, or it
  does not exist

found 1 skill(s) and did NOT migrate any of them (0 yours + 1 aef's own):
  SKILL    .claude/skills/new-model-check/SKILL.md   (aef's own — not yours)
```

The `0 yours + 1 aef's own` split is worth naming as a thing that works: the
only skill in the repo is the one `adopt` wrote ninety seconds earlier, and
`migrate` says so rather than reporting a skill the owner would go looking for.

**The generated stub is not usable, and says so:**

```python
# No wrappable call site was found. See the command's report for what was
# skipped and why — an empty file here is a finding, not a failure.

def build_graph() -> Graph:
    raise NotImplementedError(
        "aef migrate found no wrappable call site in this repo. Nothing was "
        "generated, deliberately, rather than emitting a graph that does nothing."
    )
```

### The finding, in one paragraph

**After ten minutes, the owner of an agentless repo has seventeen documents, a
config template, a workflow pair, and a `build_graph()` that raises — and every
one of the six commands `FIRST_DAY.md` tells them to run next needs a graph
that exists.** The kit is honest about this at every point where it could have
hidden it: `migrate` prints `found 0 call site(s)`, the generated module's own
docstring calls an empty file "a finding, not a failure", `build_graph` raises
with the reason rather than returning an empty graph, and `FIRST_DAY.md` says
in its second paragraph that the node bodies are "the one gap no command
closes". The one place the documents are *not* honest is small and real:
**checklist item 3 tells this owner to "identify your current entrypoint(s) —
the function(s) that start an agent run" two lines above item 5, which says
"no legacy code to migrate."** Item 3 lives in `render_migration_checklist`'s
`common` list and is emitted for every framework including `none`
(`aef/cli/adopt.py:1005`), so on a repo that by construction has no such
function it is an instruction nobody can carry out, printed to the terminal and
written into `AEF_MIGRATION_CHECKLIST.md`. **F-N7-3 (LOW)**, reported not
fixed. And `aef loop doctor` at this point is 1 of 6 obligations met
(`03-doctor-coldstart.txt`) — the one being "model calls visible", which is
trivially true of a repo that makes none.

## 2. L1's fix, on a real `master` repo

ADR 0189 replaced a hard-coded `main` with a derivation. peptideindex is the
first repository it has been exercised on where the two answers differ. Three
measurements, and one counterfactual.

**The cycle, with `--base` left at its default** (`04a-cycle-default-base.txt`):

```
$ aef loop cycle --repo . --state <W>/state --workdir <W>/wd --corpus corpus \
    --agent-path agents/migrated/graph.py --no-memory
  preflight: 5 of 6 obligation(s) unmet …
  ledger verified: 0 entr(ies)
  no memory store configured: nothing to learn from, no candidate
cycle verdict: … (--no-memory was passed: this cycle could not propose)
EXIT=0
```

It ran. That is the whole point — before ADR 0189 this command would have
resolved `main`, and `main` does not exist here.

**The counterfactual, `--base main`** (`04b-cycle-base-main.txt`):

```
EXIT=3
error (BaseRefError): base ref 'main' does not exist in <repo>. This
repository's branches are: master. Pass --base <ref> naming one of them; the
default is this repository's own default branch (origin/HEAD, else the branch
you are on), not the literal 'main'.
```

**Which term answers** (`04c-base-ref-derivation.txt`, `23-base-ref-real-repo.txt`):

```
FALLBACK_BASE_REF (the literal used when the repo has no answer) = 'main'

== arm 1: the safety clone (origin removed)
   remotes:              (none)
   origin/HEAD:          fatal: ref refs/remotes/origin/HEAD is not a symbolic ref
   HEAD is on:           master
   resolve_default_base_ref -> 'master'          <- term 2

== arm 2: a clone of the clone (git writes origin/HEAD)
   origin/HEAD:          refs/remotes/origin/master
   resolve_default_base_ref -> 'master'          <- term 1

== /Users/raptor/peptideindex (the owner's checkout, read-only)
   origin/HEAD                 : origin/master
   HEAD is on                  : aef/adopt
   resolve_default_base_ref -> : 'master'        <- term 1, while HEAD is elsewhere
```

The third is the one that matters most, because it is the property ADR 0189
gives as term 1's *reason* — the default must not move when the operator checks
something else out — measured on a repository with sixteen branches and a real
remote rather than on a fixture.

And it reached the audit trail. The `proposed` ledger event of §6's cycle:

```json
{"kind": "proposed",
 "detail": {"base": "master", "head": "loop/cycle-20260905T104502-prompt",
            "paths": [".claude/agents/price-freshness-reviewer.md"]}}
```

## 3. One persona, as the owner's proxy

`.claude/agents/price-freshness-reviewer.md` (committed in full at
`docs/research/pilot-peptide/persona-price-freshness-reviewer.md`). It reviews
one vendor/compound pair's captured price rows and rules on whether the site
may display the lowest as current, under four rules **all taken from this
repo's own code and commit history**: `STALE_AFTER_DAYS = 7`
(`site/assets/js/kpi-format.js`), *label-do-not-hide* (commit `5752fcf3e`), the
`price_per_mg_usd > 300` plausibility cap (`db/price_outlier_cap_views.sql`),
and single-vial-not-bulk (the same file's U+00D7 multipack predicate). It must
close with one machine-readable verdict line.

**The justification, in one sentence a reader could dispute:** peptideindex's
own HEAD commit is a price-freshness disclosure fix whose message says it
leaves the root cause in place — `v_listing_current` is "latest row per
listing" with no upper bound on age — while **4,183 of 13,806 vendor/compound
pairs were 3+ days stale and 1,342 were over 30 days**, so deciding per
compound whether a captured price may still be shown as current is a judgement
this repo makes by hand today, and this persona is that judgement written down.
**The dispute a reader would raise is fair:** a 7-day threshold is arithmetic,
it is already implemented twice (in `kpi-format.js` and in the view), and an
owner could reasonably say the whole job is a SQL predicate and needs no
reviewer at all. §6 shows what the reviewer is actually for — three of the five
questions turned on something the threshold cannot answer (a missing date, a
bulk tier, a row two cents under a cap) — and that is an argument, not a proof.

`aef migrate --dir .` then found it (`05-migrate-persona.txt`):

```
found 1 prompt agent(s) under .claude/agents
  AGENT    price-freshness-reviewer  (.claude/agents/price-freshness-reviewer.md)
            -> agents/migrated/price_freshness_reviewer/graph.py
            graph_id='price-freshness-reviewer', wired retrieve -> prompt_agent
              -> reflect -> consolidate -> END
```

`migrate` ran at the default root, and `--agent-root .claude/agents` was passed
to every `aef loop` command instead — ADR 0158's R1 workaround, unchanged from
ADR 0163 §2 and for the same reason (the generated module must be
dotted-importable).

## 4. `aef.yaml`, the owner's opt-in, and five real objectives

```yaml
model_provider:
  impl: claude_code
  model: ""            # empty = the session default the harness itself picks
gates:
  live_model_calls: true
objectives: "Rule on whether one vendor/compound pair's captured price rows may
  still be displayed as a current price, under this repo's own freshness,
  plausibility and pack-tier rules."
```

`gates.live_model_calls: true` is the owner's opt-in and nothing less (ADR
0181). **What it permits, in the owner's terms:** the gates' sandbox worker —
the one process in this repo that executes code an agent wrote — gains
`sandbox.HARNESS_LOGIN_ENV`, so a candidate's model calls run under this
machine's harness login and **spend this operator's quota**. It is read from
the base ref so a candidate cannot grant it to itself, and it is recorded on
every `gated` ledger event (`live_model_calls: true`, §6). Without it
`--cassette-miss live` is refused by name, and a changed prompt is a changed
cassette key, so it is the only honest way to score a prompt candidate at all.

Five objectives, every row real and traceable to a named file
(`05-objectives-and-answers.txt`). The "Today is …" date is stated in each
objective because a tool-less single-turn completion has no clock — a decision
that turns out to matter, see §6.

| | objective (abridged) | first line of the answer | verdict line |
|---|---|---|---|
| O1 | *peptideplugs.com / tirzepatide, one quantity-1 row at $1.6667/mg, `scrape_date` 2026-08-12, today 2026-09-05; the storefront now 404s. May the profile display $1.67/mg as current?* (the HEAD commit's own live case) | `**Age:** 24 days, measured from `scrape_date` 2026-08-12 against today 2026-09-05 (UTC). That is at or past `STALE_AFTER_DAYS = 7`, so this pair is **stale**.` | `VERDICT: STALE — tirzepatide @ peptideplugs.com, as of 2026-08-12, 24 days old` |
| O2 | *evolvebiopep.com / tirzepatide, $1.6665/mg, `scrape_date` 2026-08-12, today 2026-08-14 (the snapshot's own `generated_at`). Does this pair need the "As of" chip?* | `## Ruling` | `VERDICT: FRESH — tirzepatide @ evolvebiopep.com, as of 2026-08-12, 2 days old` |
| O3 | *`price-index.json` reports bpc-157 min 1.96 / median 6.698 / **max 299.98** across 138 vendors; the view excludes `> 300`. Does the row behind 299.98 survive the cap as written?* | `## Ruling` | `VERDICT: STALE — bpc-157 @ unknown (vendor not present in price-index.json), as of unknown, unknown days old` |
| O4 | *peptaura.com / bpc-157, two rows on the same vial dose: `10 × 10mg vials` @ $0.96/mg and `10mg vial` @ $1.966/mg, both `scrape_date` 2026-08-14, today 2026-08-14. Which may the site display?* | `**Display $1.966/mg — the "10mg vial" row.**` | `VERDICT: STALE — bpc-157 @ peptaura.com, as of 2026-08-14, 22 days old` |
| O5 | *skyepeptides.us.com / bpc-157 at $1.96/mg; the committed vendor doc's `compounds` entries carry no `as_of` and no `scrape_date` reached the document. May the profile display it as current?* | `**Ruling: display it, but with the "As of" chip in its unknown-date form — not as a current price.**` | `VERDICT: STALE — bpc-157 @ skyepeptides.us.com, as of unknown, unknown days old` |

**5 calls.** 211–394 words each. Containment recorded on every one, and this is
the first live end-to-end exercise of ADR 0190's recorder fix (`06-runs-inspected.txt`):

```
model_calls=1  provider_name='claude_code'
provider_isolation=['no_mcp','no_project_context','no_tools','single_turn','system_role']
containment={'isolation': [...same five...], 'persona_role': 'system', 'provider': 'cassette'}
runs=5  with a cassette=5  with a declaration=5
```

ADR 0190 named exactly this as its lowest-confidence claim — *"the pilot itself
was not re-run … the one input not exercised end to end is the live
`claude_code` subprocess"*. It is exercised now, five for five, and the
recorded declaration is the provider's real five-element set rather than a
stub's three.

## 5. `harvest` — and F-N7-1

```
$ aef loop harvest agents.migrated.price_freshness_reviewer.graph \
    --runs <W>/runs --corpus corpus --state <W>/state
promoted 0 run(s) to the train split
  5 passed, not promoted: 1ddcad17…, 33108d40…, 7961a9cf…, 7e3962c3…, fef4beb1…

$ … --include-successes
promoted 1 run(s) to the train split
  4 REJECTED, did not re-execute deterministically: 1ddcad17…, 33108d40…,
    7e3962c3…, fef4beb1…
```

The first line is correct (harvest promotes failures unless asked otherwise,
ADR 0060). The second is the finding, and it is a **new** one: all five runs
carry a cassette and the recorded provider declaration, so neither F-M6-1 nor
F-M6-2 is the cause. One run of five is admitted, and it is not the first
alphabetically or the last chronologically — it is the first run in *time*.

### F-N7-1 (HIGH) — the determinism re-check does not reproduce the memory the run read

`harvest._reexecution_services` reproduces the clock (ADR 0126), the model and
the cassette (ADR 0126), and the provider's isolation declaration (ADR 0190).
It does not reproduce the durable memory:

```python
return agent_services(
    clock=_fixed_clock(scenario),
    memory=InMemoryMemoryStore(),      # <- always empty
    model_provider=cassette,
)
```

Since ADR 0118 every `aef migrate`-generated prompt-agent graph is wired
`retrieve -> prompt_agent -> …`, and `prompt_agent_fn` appends what `retrieve`
found **to the user turn**. So the request depends on the store, the store
grows with every run, and the re-check always replays against an empty one.

**The divergence, byte for byte** (`diff_request.py`, offline):

```
recorded messages: [('system', 3045), ('user', 625)]
re-executed     : [('system', 3045), ('user', 481)]

--- role system: identical (3045 chars)
--- role user: DIFFERS (625 -> 481 chars)
   --- recorded
   +++ re-executed
    Today is 2026-08-14 (UTC) — … Reviewing evolvebiopep.com / tirzepatide. …
   -
   -Lessons from this agent's earlier runs (most relevant first):
   -- [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
```

A different user turn is a different cassette key, so the replay misses and the
run is rejected as flaky — the rejection ADR 0190's own docstring calls "a
correct-looking rejection for the wrong reason", in a second spelling.

**It is monotone, which is what makes it a rule rather than a flake:**

```
at 2026-09-05T10:31:17  run 7961a9cf  user_chars 598  lessons 0   <- the only admitted run
at 2026-09-05T10:31:45  run 1ddcad17  user_chars 625  lessons 1
at 2026-09-05T10:32:18  run 33108d40  user_chars 731  lessons 2
at 2026-09-05T10:32:39  run fef4beb1  user_chars 761  lessons 3
at 2026-09-05T10:32:55  run 7e3962c3  user_chars 889  lessons 4
```

**Stated plainly: with a durable `--memory`, only the FIRST production run
against a given store is harvestable, and every run after it is rejected as
non-deterministic.** The adopter's own generated cron passes `--memory` and
`--record-runs` to the same deployment, which is the configuration this
describes.

**Isolated to one variable** (`arms_harvest.py`, offline, zero live calls, no
file under `aef/` edited — arm 1 patches `_reexecution_services` in that
process only, seeding the memory with the records written by the runs that ran
*before* this one):

```
== arm 0-as-shipped
   promoted 1 run(s) to the train split
     4 REJECTED, did not re-execute deterministically: 1ddcad17, 33108d40, 7e3962c3, fef4beb1
== arm 1-memory-the-run-saw
   promoted 5 run(s) to the train split
```

**One observation reported without a claim of harm:** the lesson that made four
runs unharvestable is `- [success] no failure signals: 0 error(s) recorded, 0
tool call(s), none failed` — a retrieved "lesson" with no content, spending
context budget and, here, the whole ingestion path.

**The operator workaround, and its cost.** Re-running the four objectives with
no `--memory` makes each one the first run against an empty store, and all five
then harvest as shipped (`09-harvest-all.txt`, **4 live calls**):

```
promoted 4 run(s) to the train split
  1 already in the corpus: 7961a9cf-8ade-4ec1-83c9-2cb22f026426
```

That is the corpus §6 gates against, and it is honest about what it is: five
real objectives from this repo's data, answered live by the real harness,
admitted by `harvest`. It is also a workaround that switches off the durable
memory the loop exists to accumulate, which is why F-N7-1 is HIGH and not
cosmetic.

### The redaction scan, and its control

`08-redaction.txt`, the shipped `RedactionPolicy`.

```
policy patterns: email, api_key, bearer, aws_key, opaque_secret
working_memory keys dropped outright: ['api_key', 'token', 'secret', 'password']

== 1. what harvest itself counts, with redaction ON (the shipped default)
   arm 0 — as shipped
     re-executed  : 5      admitted : 1      rejected (non-deterministic) : 4
     refused (behaviour changed under redaction) : 0
     refused (a secret survived redaction)       : 0
     redactions (substitutions made)             : 0
   arm 1 — + the memory the run saw
     re-executed  : 5      admitted : 5      rejected (non-deterministic) : 0
     refused : 0 / 0       redactions : 0

== 2. the policy applied directly to all five runs
   every run: INPUT subs=0  ANSWER subs=0  labels matched in working memory=[]
   totals: {"answer_subs": 0, "input_subs": 0, "wm_dropped": 0}
```

**Nothing was redacted and nothing refused, and a zero is exactly what a dead
scanner produces**, so the control was run:

```
== 3. the control
   email          substitutions=1  -> ... Escalate to [REDACTED:email].
   api_key        substitutions=1  -> ... Escalate to [REDACTED:api_key].
   bearer         substitutions=1  -> ... Escalate to [REDACTED:bearer]
   aws_key        substitutions=1  -> ... Escalate to [REDACTED:aws_key].
   opaque_secret  substitutions=1  -> ... Escalate to [REDACTED:opaque_secret].

   secret-shaped working-memory keys:
     before ['api_key', 'token', 'vendor_domain'] -> after ['vendor_domain'] (count=2)
```

**5 of 5 shapes caught, 2 of 3 keys dropped. The scan scans.**

**What it did NOT match, on a repo whose content is vendor names and prices:**

```
   vendor domain                substitutions=0  -> peptideplugs.com
   vendor domain (multi-label)  substitutions=0  -> skyepeptides.us.com
   compound slug                substitutions=0  -> bpc-157
   price per mg                 substitutions=0  -> price_per_mg_usd 1.6667
   scrape date                  substitutions=0  -> scrape_date 2026-08-12
   a whole real row             substitutions=0  -> peptaura.com / bpc-157 "10 × 10mg vials" @ $0.96/mg, 2026-08-14
   an operator email in prose   substitutions=1  -> reached [REDACTED:email] about the delisting
   an azure subscription UUID (shape only)  substitutions=0
   a bare UUID (shape only)     substitutions=0
```

Two things follow, and they point opposite ways. The vendor domains, prices,
compound slugs and scrape dates are **public data this site exists to
publish**, so not redacting them is right and a policy that did would empty
every scenario of the thing it tests. The UUID is **ADR 0163's residual, on a
second repo**: this repo commits an Azure subscription id in `infra/jobs/*.yaml`
(the value is deliberately not reproduced here — the shape is), hyphenated, and
`opaque_secret` excludes `-` since ADR 0126 corrected a false positive. Two
repos in a row have had UUID-shaped secrets the default list does not cover;
that is a pattern an adopter must extend, and `RedactionPolicy` takes the
patterns as data so they can.

**Both policies were run over this pilot's own artefacts before they were
committed** (`24-artefact-scan.txt`): the 5-pattern policy on this branch and
the 10-pattern one on the trunk. Every hit is accounted for by name — 11
distinct UUIDs, all of them run ids, scenario ids or the scratchpad session
directory; 3 `opaque_secret`, being the ledger's own two hash-chain digests
and one deliberately planted control token; 1 `api_key` and 1 `email`, both
planted controls in `redaction_scan.py`. No real credential is committed.

**A false positive worth recording, found by that same scan**: `opaque_secret`
matches
`224f5c867a6e/scratchpad/w/n7/peptide/CLAUDE` — a filesystem path — and the
ledger's own `entry_hash`. ADR 0126 narrowed this pattern once for exactly this
class of miss; it still fires on a long path segment.

## 6. Owner checks, `bless`, `doctor`, and one cycle

### The checks — three rules, values computed, not typed

`add_checks.py` is committed and is the definition. Each rule is written once
and applied to every scenario; rules 2 and 3 carry a per-scenario value derived
by arithmetic from that scenario's own objective and the persona's own stated
thresholds.

1. **Shape.** The answer must end with the verdict line the persona requires.
   *Disputable*: a human reading the prose gets the answer either way, so an
   owner could call the format cosmetic.
2. **Age.** The day count **on that verdict line** must be
   `floor(stated "Today is" − newest stated scrape_date)`, or `unknown`.
   *Disputable, and this is the dispute an owner would actually have*: the
   reviewer could be held right to prefer the real current date over the one
   the message states, in which case the check is wrong and the model is not.
3. **Verdict token.** `EXCLUDE` iff a stated `price_per_mg_usd` exceeds 300;
   else `STALE` if the age is unknown or ≥ 7; else `FRESH`.
   *Disputable, sharply*: on the $299.98/mg row the model ruled `EXCLUDE` while
   stating in the same answer that the row clears the cap by two cents,
   reasoning from the cap's rationale rather than its threshold. Many owners
   would call that the better answer.

**Disclosure** (ADR 0163's term): the recorded answers were read before the
rules were written, to know whether a failure was reachable at all. All three
then come from the persona's own text and were applied unchanged.

**A control that had to be tightened, recorded because the method has that
rule.** Rule 2's first draft was a `contains` over the whole answer, and it
**passed on all five** — including the one whose verdict line carries the wrong
number, because that answer discusses the right number in a caveat paragraph
two lines above the wrong verdict. A control a long prose answer can satisfy by
mentioning the answer somewhere is not a control. It was anchored to the
verdict line; it was never loosened.

```
$ aef loop score agents.migrated.price_freshness_reviewer.graph --corpus corpus \
    --config aef.yaml --memory <W>/state/memory.jsonl
  model calls: 5 cassette hit(s), 0 miss(es), on_miss=fail — replayed
  train  n=5  with_checks=5  mean=0.8000 stdev=0.2981 ci95=[0.5387, 1.0613]
      1.0000  013c9044   1.0000  028299cf   1.0000  7961a9cf
      0.3333  ddfe4cc1     check failed: … regex '(?m)^VERDICT: .*, 0\ days\ old…'
                           check failed: … regex '(?m)^VERDICT: FRESH [—-] '
      0.6667  fd9c9064     check failed: … regex '(?m)^VERDICT: STALE [—-] '
```

Zero live calls. **Two of five scenarios fail, and the two failures are
interesting rather than manufactured.** On O4 the model wrote, in the answer
itself:

> **One caveat on the date.** Your message states today is 2026-08-14, which
> would make these rows 0 days old and FRESH. My environment reports today as
> 2026-09-05. … I rule on the conservative reading rather than assuming
> recency.

It named the conflict, chose its own clock over the stated date, and put the
consequence in the verdict line. On O3-successor it ruled `EXCLUDE` on a row it
had just shown survives the cap. Neither is a hallucination; both are a
reviewer disagreeing with its brief, which is exactly the thing owner checks
exist to catch and exactly the thing a reader may say the checks get wrong.

Both failures reached memory under **one signature** (ADR 0174 keys a check by
`check:<path>:<op>` without its value, which is what makes ADR 0110's two-run
threshold reachable across scenarios failing the same field for different
reasons):

```
failure | ddfe4cc1-47a | checkfail-aa86d9e4cf0cea | ['check:working_memory.prompt_agent:regex']
failure | fd9c9064-003 | checkfail-d1fad4b45c0196 | ['check:working_memory.prompt_agent:regex']
```

### `bless` and `doctor`

```
$ aef loop bless … --graph-id price-freshness-reviewer --agent-root .claude/agents \
    --agent-path .claude/agents/price-freshness-reviewer.md
blessed .claude/agents/price-freshness-reviewer.md as baseline v1 for graph
  'price-freshness-reviewer'
  G5 now has a reference point to measure drift against.

$ aef loop doctor …
Loop readiness — 6 things you must supply
  [--] corpus + tripwire       5 scenario(s), 0 tripwire(s)
  [OK] reflect node routed to  agents/migrated/price_freshness_reviewer/graph.py:
                               make_prompt_agent_node(route='reflect') builds a node
                               that routes to it
  [OK] observations            9 recorded run(s) at <W>/state/observations.jsonl
  [--] halt channel            none — a halt would tell nobody
  [OK] blessed baseline        1 archived version(s) of '.claude/agents'
  [OK] model calls visible     2 graphs scanned, none reaches a model SDK the
                               harness cannot see
```

**4 of 6, up from 1 of 6 at cold start.** Obligation 2 resolved the *persona*
to the *graph* `migrate` generated for it (ADR 0178's R2). The two unmet are
the owner's to supply and neither was faked: a tripwire is a live call and a
judgement about "a task beyond this agent", and a halt webhook is
infrastructure.

### One cycle, live

```
$ aef loop cycle --repo . --state <W>/state --workdir <W>/wd --corpus corpus \
    --runs <W>/runs2 --module agents.migrated.price_freshness_reviewer.graph \
    --proposer rule_based_prompt --agent-root .claude/agents \
    --agent-path .claude/agents/price-freshness-reviewer.md \
    --entrypoint agents.migrated.price_freshness_reviewer.graph:build_graph \
    --memory <W>/state/memory.jsonl --config aef.yaml --cassette-miss live \
    --build-command "python -c pass"

  --graph-id not given; the evidence graph id is derived as
    'price-freshness-reviewer' from the 5 scenario(s) in corpus, which record one
    graph. The archive key is unchanged ('default'), so a blessed baseline stays
    where it was blessed (ADR 0182)
  preflight: 2 of 6 obligation(s) unmet (corpus + tripwire, halt channel).
  ledger verified: 2 entr(ies)
  promoted 0 run(s) to the train split
    5 already in the corpus: 013c9044…, 028299cf…, 7961a9cf…, ddfe4cc1…, fd9c9064…
  proposed cycle-20260905T104502-prompt on local branch
    loop/cycle-20260905T104502-prompt (never pushed; proposer=rule_based_prompt)
  gated: reject — G3 rejected it: 1 previously-passing scenario(s) now score
    below 0.5 (zero tolerance, regardless of the aggregate)
EXIT=1
```

The harvest leg ran, which is ADR 0190's F-M6-3 fix working: `--runs` with
`--module` is no longer a silent no-op, and it reported the honest reason for
promoting nothing.

**The diff, in full** — one bullet, four lines, one file (`16-diff.txt`):

```diff
--- a/.claude/agents/price-freshness-reviewer.md
+++ b/.claude/agents/price-freshness-reviewer.md
@@ -64,3 +64,7 @@
+
+## Lessons (aef)
+
+- <!-- aef sig=failure:check:working_memory.prompt_agent:regex runs=2 --> 1
+  error(s) recorded; 0/0 tool call(s) failed. errors[0]: check failed:
+  working_memory.prompt_agent does not match the pattern the owner declared;
+  observed 368 words, 2138 chars
```

Note what is not in it: any of the model's own text, and none of the check's
own pattern. ADR 0180's finding 2 and ADR 0174's rule, both holding on a repo
neither of them touched.

**The `gated` ledger event, in full** (`17-ledger.txt`):

```
live_model_calls: true
proposer: rule_based_prompt
evidence: 7 corpus pass(es) (35 scenario execution(s)): 1 candidate + 1 incumbent
          + 5 random control(s); corpus records one graph
          ('price-freshness-reviewer'); gating all 5 gated scenario(s)
G0 pass  1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically scanned,
         no violations; 1 NOT statically scanned (not Python — an AST gate has
         nothing to say about them, and G1/G2/G5 judge them instead)
G1 pass  1 build command(s) succeeded against the merged workspace
G4 pass  no owner-only safety metadata declared by the candidate
G5 pass  0/3 accepted in the last 7d; drift 0.057/0.500 from the blessed baseline
G2 pass  5 scenario(s) re-executed; every previously-passing one still passes.
         0 changed routing (reported, not rejected).
G3 fail  1 previously-passing scenario(s) now score below 0.5 (zero tolerance,
         regardless of the aggregate)
grounded_in:
  checkfail-aa86d9e4cf0cea60604f7db8137d3755 (memory):
    failure:check:working_memory.prompt_agent:regex recurred
  checkfail-d1fad4b45c0196ce84c478e7230be16f (memory):
    failure:check:working_memory.prompt_agent:regex recurred
kinds: ['blessed', 'blessed', 'proposed', 'gated', 'rejected']
```

**Verdict: REJECT, by G3. Drift consumed: 0.057 of 0.500. 35 scenario
executions, 30 of them live cassette misses served inside the gates' worker.**
The 30 follows from the cohort and is an inference, stated as one: the
incumbent's five hit the cassette because its persona is byte-identical to the
recording's, and the candidate's five plus the five controls' twenty-five are
all changed prose and therefore changed cassette keys. No call count reaches
the ledger — ADR 0191's F7 says why, and says it is not fixable without
changing four dataclasses.

**G2 passed while G3 failed**, the same separation ADR 0162 measured and ADR
0163 reproduced on marlin: G2 asks whether the outcome classification changed
and G3 asks what the score is, and a scenario keeps its `passed` label while
its check fraction collapses. A lesson bullet made a previously-passing
scenario worse, on a third repo, with the model's own words already removed
from the bullet.

### **The cycle grounded in harvested evidence** — clause (b), checked

This is N1's unclaimed clause and the thing this pilot exists to answer, so it
was followed link by link rather than asserted (`21-grounding-chain.txt`):

```
  checkfail-aa86d9e4cf0cea60604f7db8137d3755
    memory record kind   : failure
    failed_checks        : ['check:working_memory.prompt_agent:regex']
    its run_id           : ddfe4cc1-47a7-43f0-92a2-fcee28a8fd35
    a corpus scenario?   : yes
    that scenario source : harvest
    its objective        : Today is 2026-08-14 (UTC). Reviewing peptaura.com / bpc-157…

  checkfail-d1fad4b45c0196ce84c478e7230be16f
    …  its run_id : fd9c9064-…   source : harvest
    its objective        : Today is 2026-08-14 (UTC). site/assets/data/price-index.json…

every cited record's run is a corpus scenario whose source is `harvest`: True

the corpus, by source:
  {"harvest": 5}  (bootstrap: 0, record: 0)
```

**Both records the proposer cited are check failures of production runs that
`aef loop harvest` re-executed and admitted, and the corpus contains nothing
else.** ADR 0163 §7 had to say the opposite in full — *"`harvest` admitted
nothing, so `bootstrap` populated the corpus"* — and ADR 0190 explicitly
declined to claim clause (b). It is claimed here, with the chain.

### `monitor` and `digest` — and F-N7-2

```
$ aef loop monitor …
checked 0 merged change(s)
  cycles run: 3 (last 0.0 day(s) ago)
  last PROPOSED: 0.0 day(s) ago
  last KEPT/MERGED: never
```

```
$ aef loop digest … --runs <W>/runs2 --graph-id price-freshness-reviewer
# Self-rewiring digest, 2026-08-29 to 2026-09-05
- Proposed: 1
- Merged: 0 (acceptance rate 0%)
- Rejected: 1
- Scenarios added to the corpus: 0
- Drift from the blessed baseline: 0.000
- Production runs recorded: 5
- Halt channel configured: NO

**No halt channel is configured.** …

**5 recorded, 0 admitted to the corpus.** Recording is not harvesting: … one is
not: `REJECTED, did not re-execute deterministically` on every run means the
ingestion path is broken, not quiet.
```

**That warning is false on this repo on this day.** `aef loop harvest` admitted
all five, minutes earlier, into the corpus in this repository, and the digest
tells the owner to run the command that already succeeded.

#### F-N7-2 (MEDIUM) — `Scenarios added to the corpus` is a constant 0

Three arms, one variable each, all through the real CLI
(`repro_digest.py` / `20-digest-defect.txt`, zero live calls):

```
the corpus in this repository: 5 scenario(s), by source {"harvest": 5}

== arm 0 — can the command be TOLD which corpus to look at?
   `aef loop digest ... --corpus corpus` -> EXIT=2
   aef: error: unrecognized arguments: --corpus corpus

== arm 1 — does anything compute the number?
   'scenarios_added' appears in aef.harness.loop.digest's body : False
   'corpus' appears in it                                      : False
   build_digest's default for scenarios_added                  : 0

== arm 2 — the same command, corpus present vs corpus emptied
   5 harvested scenarios present : - Scenarios added to the corpus: 0   (ADR 0190 warning printed: True)
   corpus emptied to 0           : - Scenarios added to the corpus: 0   (ADR 0190 warning printed: True)
   identical                     : True
   corpus restored               : 5 scenario(s), 5 from harvest
```

`loop.digest()` calls `build_digest(...)` without `scenarios_added`, so the
value is the parameter's default in every invocation there has ever been; the
`digest` sub-parser has no `--corpus` at all, so the command has no way to see
one. The number was cosmetic while nothing read it. **ADR 0190 then keyed a
warning off it** — closing ADR 0163 §10's complaint that the digest drew no
line between two numbers — and the line it drew is drawn from a constant. The
corpus was emptied and restored under a `shutil.copytree` backup and the
restore verified by `git status --porcelain` on the clone coming back clean.

## 7. The real repo, on a branch

`/Users/raptor/peptideindex`, on `aef/adopt` cut from `master`
(`22-real-adopt.txt`). `master` was not modified and was never checked out
again.

```
$ git -C /Users/raptor/peptideindex status --porcelain
?? .playwright-cli/
?? output/

$ git -C /Users/raptor/peptideindex log master..aef/adopt --oneline
4e2c3eb9c chore(aef): adopt the AEF scaffold (aef adopt --dir .)

$ git -C /Users/raptor/peptideindex rev-parse master
5752fcf3e29d861abb05b662a34960633ee49e76      (unchanged)

$ git -C /Users/raptor/peptideindex diff --stat master aef/adopt | tail -1
 16 files changed, 2691 insertions(+)
```

**Exactly the two pre-existing untracked paths, exactly one commit, zero
deletions, nothing pushed.**

**The undo, one line:**

```
git -C /Users/raptor/peptideindex branch -D aef/adopt
```

(the checkout is left on `aef/adopt` by instruction, so the owner leaves the
branch first — `git -C /Users/raptor/peptideindex checkout master` — and then
deletes it; the branch is not merged anywhere and `-D` is the whole undo).

**One deviation from the brief's own wording, and it is deliberate.** N7 says
`git add -A && git commit`. **`git add -A` would have staged
`.playwright-cli/` and `output/`** — 18 files, 548K, the owner's untracked
working directories — into a commit about adopting a scaffold, and the brief's
own verification line says those two paths must still show as untracked
afterwards. The sixteen adopt-written paths were staged by name instead. This
is worth an adopter's attention rather than only a footnote: **the natural
adopt-then-commit gesture sweeps whatever the owner has left lying around**,
and `aef adopt` prints the exact list of what it wrote.

## 8. What still requires a person

1. **A third party.** peptideindex is the owner's own repository, not a
   tenant's. The runs are real, the repo is real, the data is production data —
   and every objective was written by the same process that read the repo. The
   trust case's criterion 6 says "real tenants", and a tenant is someone else.
   Unclaimed, in the rubric row, in those words.
2. **A tripwire and a halt channel.** Two of six obligations, both unmet, both
   the owner's: a tripwire costs a live call and a judgement about what is
   beyond this agent, and a halt webhook is infrastructure this pilot must not
   invent.
3. **F-N7-4, before this branch merges.** ADR 0197's `uuid` pattern and this
   pilot's own corpus cannot both stand: on the trunk, `harvest` refuses every
   run for carrying its own identifier. Whoever owns 0197 decides where the
   scan runs; the reproduction is committed either way.
4. **F-N7-1.** Until it is closed, an adopter who follows the generated cron —
   `--record-runs` and `--memory` on the same deployment — harvests exactly one
   run, ever. The workaround (drop `--memory`) switches off the durable memory
   the loop exists to accumulate.
5. **The redaction list for this repo.** The base policy does not match this
   repo's Azure subscription UUID, the same gap ADR 0163 named on marlin —
   **closed on the trunk by ADR 0197**, at the cost F-N7-4 measures.
6. **Whether the persona's job is a job.** §3's justification is an argument an
   owner can reject. Only its owner can say whether a price-freshness reviewer
   earns a model call per compound, or whether the 7-day rule belongs in the
   view and nowhere else.

## 9. The rubric

**Dimension 7: 3 → 5.** The falsification N7 pre-registered had three clauses
and all three fired:

- **real runs of a real repo's real job entered the corpus through `harvest`** —
  5 of 5, `source: harvest`, redaction counts quoted (§5), control passed 5/5
  shapes and 2/3 keys;
- **a candidate was proposed grounded in those harvested records** — both cited
  records' runs are harvest-sourced corpus scenarios, chain in §6, and the
  corpus contains nothing from `bootstrap` or `record`;
- **the gates reached a verdict on it live** — `live_model_calls: true`, six
  gates, REJECT by G3, drift 0.057/0.500.

**Not claimed, and the reason, in the row itself: peptideindex is the owner's
own repo, not a third party.** That is what the remaining five points are for,
and no amount of work on this machine can earn them.

Two honest qualifications inside the +2. Four of the five harvested runs were
re-recorded without `--memory` because F-N7-1 rejects them otherwise; they are
the same objectives, the same persona and the same live harness, and the
workaround is named where it happened rather than smoothed. And the two
grounding records come from one check signature on one failure family.

## 9a. F-N7-4 (HIGH) — ADR 0197 closes the path this pilot opened

Found at commit time, not during the pilot: worker **N5** landed ADR 0197 on
the trunk an hour after §5 named the UUID as this repo's redaction residual,
and it added a `uuid` pattern that cites ADR 0163 for exactly that reason. It
is the right pattern for the right reason and it has a consequence nobody
measured: **a recorded run's own id is a UUID.**

`aef run --record-runs` names each file `<uuid4>.json`, `AEFState.run_id` is
that id, and `harvest` scans the scenario it is about to write with the same
policy it redacted the input with. Two arms over the same five real runs of
this pilot, one variable — the pattern list (`repro_uuid_harvest.py`,
`25-uuid-vs-harvest.txt`, zero live calls):

```
== BASE  (5 patterns, no uuid)
   promoted 5 run(s) to the train split
   redactions=0 unredactable=0 changed_behaviour=0

== TRUNK (10 patterns, ADR 0197's uuid included)
   promoted 0 run(s) to the train split
     5 REJECTED, a secret survived redaction: 013c9044…, 028299cf…, 7961a9cf…,
       ddfe4cc1…, fd9c9064…
     5 substitution(s) made by the redaction policy
   redactions=5 unredactable=5 changed_behaviour=0
```

Where it sits, field by field (`repro_uuid_where.py`):

```
run_id = 7961a9cf-8ade-4ec1-83c9-2cb22f026426

INITIAL STATE, before redaction — every field carrying a UUID:
   run_id: ['7961a9cf-8ade-4ec1-83c9-2cb22f026426']

redact_state made 1 substitution(s); after it:
   (nothing left)

THE TRACE, which redact_state does not touch and the output scan does read:
   1 distinct UUID(s) in the recorded trace: ['7961a9cf-8ade-4ec1-83c9-2cb22f026426']
```

**Both halves are damaging and they are separate.** The input redaction now
rewrites `AEFState.run_id` to `[REDACTED:uuid]` — the identifier every join in
§6's grounding chain runs on — and the output scan then refuses the run anyway,
because the trace carries the id the state no longer does. So the corpus this
ADR reports would be empty on the trunk, and the grounding chain that earned
dimension 7's +2 could not be rebuilt today.

**Reported, not fixed, and deliberately not softened into "extend the
allowlist".** Two shapes that are both UUIDs are being asked to behave
differently: a tenant's subscription id, which must never reach the corpus, and
a run's own identifier, which the corpus is addressed by. That is a decision
about *where* the scan runs rather than *what it matches* — the harness's own
identifiers are structural fields it wrote, not tenant text it read — and it
belongs to whoever owns ADR 0197, with a control that keeps a real UUID in an
objective still refused. This ADR's job is to say that the two changes collide,
with the command that shows it.

## 10. What is pinned, and what is only written down

**Nothing under `aef/` changed and no test was added.** Every finding here is a
defect in shipped code, and this worker's brief is to report rather than fix.
F-N7-1, F-N7-2 and F-N7-4 each have a runnable reproduction committed beside
this ADR (`arms_harvest.py`, `diff_request.py`, `repro_digest.py`,
`repro_uuid_harvest.py`, `repro_uuid_where.py`); a strict xfail
pinning either would belong to the fix worker that closes it, together with the
control that says the fix is a fix.

## Green bar

```
pytest -q                                2885 passed, 7 skipped, 1 xfailed
                                         (no test added and none removed — every
                                          finding here is reported, not fixed)
mypy aef examples                        Success: no issues found in 135 source files
ruff check .                             All checks passed!
ruff format --check aef tests examples   290 files already formatted
```

`ruff check .` covers `docs/`, so the eleven scripts committed beside this ADR
are linted like any other source. Getting them clean meant formatting changes
— a split path literal, sorted imports, `zip(..., strict=False)`, one renamed
loop variable — so **each was re-run from its committed copy and its output
diffed against the artefact it produced**: `grounding_chain.py`,
`inspect_runs.py`, `mk_answers.py`, `repro_digest.py` and `add_checks.py` came
back byte-identical, and `redaction_scan.py` reproduced `admitted 1 / rejected
4` and `admitted 5 / rejected 0` exactly once its arm directories were cleared.
Two artefacts were regenerated rather than kept: `04c-base-ref-derivation.txt`,
because the clone has one more branch since §6's cycle cut it, and
`24-artefact-scan.txt`, because it scans the directory it is written into.

## Confidence

High on every reproduction: each is a command whose real output is pasted
above, and F-N7-1 is isolated to one variable with a two-arm run that flips
1-of-5 to 5-of-5 by supplying only the memory the run itself saw.

High on F-N7-4: two arms differing only in the pattern list, over the same five
real runs, 5 promoted against 0 promoted.

High that the harvest leg works end to end on a live provider: five real
`claude_code` runs, five cassettes, five recorded declarations, five admitted —
which is the sentence ADR 0190 could infer but not run.

Lower, and named: the +2 rests on one persona, one failure family and five
scenarios; the two grounding records share a signature; and the cycle's live
call count (30) is an inference from the cohort's construction rather than a
number the ledger carries.

## Addendum (orchestrator): F-N7-4 closed

The run id is not only the scenario`s `id` and `initial_state.run_id` — the harness threads it through every trace record`s `input_state.run_id` and its `context.run_id`, `trace_id` and `idempotency_key`. A path list naming each would grow silently the next time a field carries it, so `harvest._scannable` holds out the harness`s own identifiers **by value**, and `RedactionPolicy.redact_state` holds `run_id`/`agent_id` out by field path. A UUID from anywhere else is a different string and still rejects the run. Mutation-checked both ways; the corpus can be rebuilt on the trunk.
