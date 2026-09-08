# Morning report — marlin, the owner's own working repository

The first time this loop has been installed into a repository somebody uses
for real work, pointed at the job one of its eight agents actually does, and
left to run.

Everything below was on disk before anyone looked. The digest, the monitor,
the status, the lineage listing, the ledger copy and the halt-channel dump are
steps in `night.sh`, not things typed afterwards.

**The headline, before the detail: it proposed, it was gated, it kept nothing —
and an independent controlled measurement made afterwards says it was right
not to.** The candidate the loop wrote scores **0.4000** live where a placebo
bullet scores **0.8667** on the same five scenarios on the same day.

---

## 1. What ran

| | |
|---|---|
| repo | a **clone** of `/Users/raptor/marlin`, `origin` removed before anything ran |
| agent | `marlin-source`, one of the eight personas in `.claude/agents/` |
| corpus | 5 scenarios, **all from `harvest`** — bootstrap 0, record 0 |
| command | `aef loop run --turns 3 --budget-minutes 3 --candidates 2 --audit-slice 1 --cassette-miss live --graph-id marlin-source` |
| scheduled for | 2026-09-06T14:55:33Z |
| fired at | 2026-09-06T14:55:33Z |
| finished at | 2026-09-06T15:01:05Z |
| wall clock | **331 s** |
| exit | **0** |

`gates.live_model_calls: true` is the clone's own opt-in, in a committed
`aef.yaml`, read from the base ref (ADR 0181). `halt_channel:` in that same
file is an argv template appending to a log **outside** the repository (ADR
0195).

**This was the seventh attempt to start the night. All six failures are
reported rather than tidied away** (§6), because five of them were defects and
the sixth was a wall clock.

## 2. What it proposed

One candidate, one file, four lines
(`artefacts/21-candidate-diff.txt`):

```diff
--- a/.claude/agents/source-agent.md
+++ b/.claude/agents/source-agent.md
@@ -63,3 +63,7 @@
+
+## Lessons (aef)
+
+- <!-- aef sig=failure:check:working_memory.prompt_agent:regex runs=2 --> 2
+  error(s) recorded; 0/0 tool call(s) failed. errors[0]: check failed:
+  working_memory.prompt_agent does not match the pattern the owner declared;
+  observed 487 words, 3108 chars; errors[1]: check failed: … observed 487
+  words, 3108 chars
```

Note what is **not** in it: any of the model's own text. ADR 0180's rule and
ADR 0174's, both holding on a fourth repository.

Grounded, in the ledger's own words, in two harvested production runs:

```
grounded_in:
  checkfail-5c3fbb8fdcc4dce6b7e8b3855543f242 (memory):
    failure:check:working_memory.prompt_agent:regex recurred
  checkfail-ff1ba92c823fcaf0c2f16c7202d90c34 (memory):
    failure:check:working_memory.prompt_agent:regex recurred
```

Both are check failures of production runs that `aef loop harvest`
re-executed and admitted; the corpus contains nothing from `bootstrap` or
`record`.

**`--candidates 2` bought nothing, for ADR 0200's reason and not a new one**:
`RuleBasedPromptProposer` returns one proposal by construction.

## 3. What the gates said

Verbatim from `artefacts/night/attempt-6-quota-outage/27-ledger.jsonl`:

```
evidence: 7 corpus pass(es) (28 scenario execution(s)): 1 candidate +
          1 incumbent + 5 random control(s); 4/4 gated scenario(s) recorded
          from graph 'marlin-source'; 1 held back for the audit (2026-09-06)
live_model_calls: True
proposer: rule_based_prompt

G0 pass  1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically
         scanned, no violations; 1 NOT statically scanned (not Python)
G1 pass  1 build command(s) succeeded against the merged workspace
G4 pass  no owner-only safety metadata declared by the candidate
G5 pass  0/3 accepted in the last 7d; drift 0.007/0.500 from the blessed
         baseline
G2 pass  4 scenario(s) re-executed; every previously-passing one still
         passes. 0 changed routing (reported, not rejected).
G3 fail  could not judge: 4 dead call(s) of 4 scenario(s) (100%), over the
         25% ceiling. The model was not answering, so neither a pass nor a
         rejection would be about this candidate
```

**Verdict: REJECT, and the rejection is a refusal to judge.** The operator's
model quota ran out during the night, so every call inside the gates' worker
came back dead, and ADR 0185's ceiling caught it and said so. That is the gate
working: a pass or a rejection built on four dead calls would have been a
statement about the quota wearing a statement about the prompt.

Five gates did return real verdicts on the candidate, including **G2 pass** —
every previously-passing scenario still passed — and **G5**, which priced the
four-line bullet at 0.007 of a 0.500 drift budget.

## 4. What it kept

**Nothing.** `kept 0, reverted 1`. `loop/kept` never moved off the commit it
was created at, `main` is the commit it was before
(`artefacts/night/attempt-6-quota-outage/30-main-after.txt`), and the kept diff
is **0 bytes**. The candidate was archived as a stepping stone at score
0.8333.

```
turn 1: audit (2026-09-06): not read — no candidate passed the gates
stopped: wall-clock budget of 180s exceeded after 1 turn(s)
```

The audit slice was held back and never spent, for the same reason as ADR
0200: it is only read when a candidate passes.

## 5. And then the measurement the gates could not finish

The night could not judge the candidate. So it was judged afterwards, by hand,
on a live quota, with **one variable**:

| arm | persona | how scored | mean over the same 5 scenarios |
|---|---|---|---|
| incumbent | as marlin ships it | cassette replay, 0 calls | **0.6667** |
| placebo | `## Lessons (aef)` + one inert bullet | **live**, 5 calls | **0.8667** |
| candidate | `## Lessons (aef)` + **the loop's own bullet** | **live**, 5 calls | **0.4000** |

`artefacts/15-live-miss-probe.txt`, `artefacts/22-candidate-live-score.txt`.

Two things fall out, and they point in opposite directions.

**The lesson bullet is harmful, and the placebo proves it is the bullet's
text.** Appending a `## Lessons (aef)` section costs nothing (0.6667 → 0.8667
is resampling, not the section). Appending *this bullet* takes it to 0.4000,
and two scenarios the incumbent passes at 1.0000 collapse — `48572a57` to
0.3333 and `a9c8ba03` to 0.0000. This is ADR 0162's and ADR 0163's finding — a
lesson bullet making the very behaviour it describes worse — reproduced on a
fourth repository, with the model's own words already stripped from the
bullet, and this time **against a placebo control rather than only against the
incumbent**. The excerpt was never the whole mechanism, and now neither is the
section header.

**And the comparison the gates make is biased the other way.** G2 and G3 score
a LIVE candidate against a CASSETTE-replayed incumbent. On this corpus the
owner checks pin no dates, so ADR 0200's F-P1-3 asymmetry does not decay — but
resampling alone moved the incumbent from 0.6667 to 0.8667, which is **larger
than any effect the loop is looking for**. A prompt candidate on this repo is
compared against a replay that is systematically *worse* than the incumbent
actually is.

## 6. The six failed starts

Reported because five of them are defects and every one of them was invisible
to a hand-run.

| # | what happened | cause |
|---|---|---|
| 1 | proposed twice, **G5 rejected both**: *"no owner-blessed baseline … Create one with `aef loop bless`"* — after `bless` had succeeded and `doctor --graph-id marlin-source` said `[OK] blessed baseline 1 archived version(s)` | **F-Q1-3**: `bless --graph-id X` archives under `X`; `run` without `--graph-id` derives the *evidence* id from the corpus but leaves the *archive key* at `default` (ADR 0182), so G5 looked in a directory that does not exist. Three surfaces, one question, and the fix the message names is the command the operator already ran |
| 2 | every gate a `TrustBoundaryError: … must be empty` | **F-Q1-4**: a run's `--workdir` is single-use. The generated `LOOP.md` tells an adopter to use a fixed `--workdir /tmp/loop`, twice, in two worked examples |
| 3 | `G2 rejected it: 3 previously-passing scenario(s) no longer pass` | **F-Q1-5**, and my own harness error: `claude` was not on the night's `PATH`. `aef loop score` on the same tree names it on every scenario — `raised: ModelProviderError: harness executable not found: 'claude'` — and the gate turns that into a verdict about the prompt |
| 4, 5, 7 | the night's own alarm fired mid-gate (540 s, 580 s, 580 s); ledger holds `proposed` and no `gated` | the wall clock — §7 |
| 6 (part) | `error (CorpusShrankError): scenario(s) changed split … run 'aef loop corpus reconcile' by hand`, and reconcile answers `nothing to reconcile` | **F-Q1-6**: the baseline is read from the base ref, which is the stale `loop/kept`. **Fixed on the trunk while this pilot ran**, by the orchestrator, citing this pilot's reproduction |

## 7. What it cost

| | |
|---|---|
| a live call on this repo's answers | **27–34 s** (5 calls in 135 s; 5 in 169 s) |
| a gated turn | 6 × (corpus − audit slice) live calls |
| the floor, on a 5-scenario corpus | `audit_slice` caps its draw at half the TRAIN split, so gated ≥ ⌈N/2⌉ = 3 → **18 calls ≈ 560–610 s** |
| the night that completed | 331 s, 24 calls attempted, **all dead** (quota) |
| the whole increment | **≤ 96 answered live calls** of a ≤ 150 budget; 42 directly counted, ≤ 54 inferred from the gate cohort (no call count reaches the ledger — ADR 0191's F7) |

**ADR 0200's 131 s/turn does not generalise, and the reason is not the loop.**
That night's answers were 211–394 words; marlin's are 512–887, because
`marlin-source`'s output contract asks for eleven things. A turn's cost is set
by the adopting repo's answer length, and on this repo one turn is ten minutes.

Three attempts died to that, which is why it is stated as a number an adopter
can plan against rather than as an anecdote.

## 8. What the halt channel did

**Nothing, correctly.** `artefacts/night/attempt-6-quota-outage/31-halt-channel.txt`:

```
--- halt channel log ---
(the channel never fired — no file)
```

There was no halt: `status` says `kill switch : clear`, `digest` says
`Halts: 0`, and a gate rejection is not a halt criterion. What matters is that
the channel was **resolvable** — the same digest says

```
- Halt channel configured: yes — /bin/sh (3 argument(s))
```

while `aef loop doctor` on the same repository, in the same minute, says

```
[--] halt channel   none — a halt would tell nobody
     fix: set AEF_HALT_WEBHOOK in your environment (never in this repo)
```

**ADR 0200's F-P1-2, still open, reproduced on a second repository.** `doctor`
takes no `--config`, so it cannot read ADR 0195's block even in principle, and
it offers the environment variable that ADR 0195 replaced.

## 9. What a person must decide

1. **Whether the lesson bullet should exist in this form at all.** §5 is the
   third repository on which appending a recurrence-counted failure bullet
   makes the agent worse, and the first with a placebo arm isolating it to the
   bullet's text. The bullet names a field and an operator and a word count;
   it does not name the requirement, because ADR 0174 strips the check's
   expected value. For a `regex` check that leaves nothing actionable —
   ADR 0201 said the same thing about its Rule A and called it "close to
   unactionable by construction".
2. **Whether the incumbent should be scored live too.** §5's placebo arm is
   the price of not doing it: the incumbent's cassette score understates it by
   0.2 on this corpus. Scoring both live doubles the most expensive thing the
   loop does and makes the incumbent's own score noisy. Nothing here chose.
3. **The three open defects** — F-Q1-3, F-Q1-4, F-Q1-5 — each reproduced in
   §6 and each belonging to a file this worker was not to touch.
4. **Whether `marlin-source`'s job is a job.** It is argued in ADR 0204 §2
   from this repository's own files and it is an argument an owner can reject.
