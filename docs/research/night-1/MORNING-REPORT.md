# Morning report — night 1, the peptide pilot, 2026-09-06

The first run of this loop that nobody watched. It was scheduled for an
instant it did not choose, started, and left; nothing read its output or
touched it between `fired at` and `finished at`. Everything below was on disk
before anyone looked.

Every file this cites is beside this one. The night's own commands wrote
them — the digest, the monitor, the lineage listing and the ledger copy are
steps in `night.sh`, not things typed afterwards, so what a person reads in
the morning is what the job left behind.

---

## 1. What ran

| | |
|---|---|
| repo | a **copy** of `peptideindex` (ADR 0192's pilot), branch `master` |
| graph | `price-freshness-reviewer`, a persona `aef migrate` registered |
| command | `aef loop run --turns 3 --budget-minutes 3 --candidates 2 --audit-slice 1 --cassette-miss live` |
| scheduled for | 2026-09-06T11:09:33Z |
| fired at | 2026-09-06T11:09:33Z |
| finished at | 2026-09-06T11:13:56Z |
| wall clock, the run itself | **262 s** |
| exit | **0** |
| live model calls | **48** (2 turns × 24 cassette misses inside the gates' worker) |

`--candidates 2` and `--audit-slice 1` are ADR 0200's two mechanisms. Live
model calls in the gates are the pilot's own opt-in, `gates.live_model_calls:
true` in its committed `aef.yaml`, read from the base ref (ADR 0181). The halt
channel is `halt_channel:` in that same file, an argv template that appends to
`HALT-CHANNEL.log` (ADR 0195).

**This was the third attempt to start the night, and the first two are
reported rather than tidied away** (`09-attempt-1-*`, `09-attempt-2-run.txt`):

- **attempt 1 died at exit 127 in 0 s.** `night.sh` wrapped the run in
  `timeout(1)`, which does not exist on macOS. My harness, not the loop.
  Replaced with `perl -e 'alarm shift; exec @ARGV'`.
- **attempt 2 ran the loop and the loop produced nothing** — §4's finding,
  which is the most valuable thing this night produced and is the reason it
  was worth running.

---

## 2. What it proposed

One candidate per turn, twice, both the same four-line diff
(`23-candidate-diff.txt`) — and it is **byte-identical to the one ADR 0192's
hand-run cycle produced on 2026-09-05**:

```diff
+## Lessons (aef)
+
+- <!-- aef sig=failure:check:working_memory.prompt_agent:regex runs=2 --> 1
+  error(s) recorded; 0/0 tool call(s) failed. errors[0]: check failed:
+  working_memory.prompt_agent does not match the pattern the owner declared;
+  observed 368 words, 2138 chars
```

Grounded, in the ledger's own words, in two harvested production runs:

```
grounded_in: ['checkfail-aa86d9e4cf0cea60604f7db8137d3755 (memory):
               failure:check:working_memory.prompt_agent:regex recurred',
              'checkfail-d1fad4b45c0196ce84c478e7230be16f (memory):
               failure:check:working_memory.prompt_agent:regex recurred']
```

**`--candidates 2` bought nothing here, and the reason is a proposer
limitation rather than a cost.** `RuleBasedPromptProposer` returns *one*
proposal by construction — it computes the lessons, takes `fresh[0]`, and
returns a one-tuple — so a turn may try two and be offered one. The store
holds exactly one lesson signature, so there was not a second to try either.
The mechanism is exercised and measured on a fixture instead
(`01-repro-a.txt`, and the ledger roster in `test_candidates_and_audit.py`);
what this night says about it is only that it costs nothing when the proposer
has one idea. **Next increment:** a prompt proposer that returns its top *k*
fresh lessons instead of its top one.

---

## 3. What the gates said

Both turns, verbatim from `17-ledger.jsonl`:

```
G0 pass 1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically scanned,
        no violations; 1 NOT statically scanned
G1 pass 1 build command(s) succeeded against the merged workspace
G4 pass no owner-only safety metadata declared by the candidate
G5 pass 0/3 accepted in the last 7d; drift 0.057/0.500 from the blessed baseline
G2 fail 4 previously-passing scenario(s) no longer pass (zero tolerance)
```

with the evidence line:

```
evidence: 7 corpus pass(es) (28 scenario execution(s)): 1 candidate +
          1 incumbent + 5 random control(s); corpus records one graph
          ('price-freshness-reviewer'); gating all 4 gated scenario(s);
          1 held back for the audit (2026-09-06)
live_model_calls: True
proposer: rule_based_prompt
```

**Verdict both turns: REJECT, by G2.** Nothing was kept
(`22-kept-diff.txt` is 0 bytes), `loop/kept` never moved off
`ccad2eb6b0de`, and `master` is the commit it was before
(`20-master-after.txt`). The run stopped on its own rule:

```
stopped: turn 2 re-proposed a tree already rejected; the proposer has
         nothing new
```

### The finding a night produces and a hand-run does not

Last night (ADR 0192, 2026-09-05) **the same diff got `G2 pass … every
previously-passing one still passes` and was rejected by G3**. Tonight it is
`G2 fail — 4 previously-passing scenario(s) no longer pass`. The candidate did
not change by one byte.

What changed is the calendar, and the mechanism is visible in the probes:

- `05b-cassette-hit-probe.txt` — the incumbent persona is byte-identical to
  the recording, so all five scenarios are **cassette hits**: `0 miss(es)`, in
  0.15 s, mean 0.8000.
- `05-live-miss-probe.txt` — one bullet appended and the same five are `5
  miss(es), on_miss=live — LIVE`, mean 0.7333.

The pilot's owner checks pin absolute day counts —
`^VERDICT: .*, 0\ days\ old$`, `^VERDICT: .*, 2\ days\ old$` — computed from a
`scrape_date` of 2026-08-14. The model answers with **its own** notion of
today, which the harness supplies and which `fixed_clock` does not reach:
`Context.now` is pinned for the graph, the model's system date is not. So the
live arm said *"Today is 2026-09-06 … that is 25 days"* where the check wants
*"2 days"*.

**Stated plainly: G2 compares a LIVE candidate against a CASSETTE-REPLAYED
incumbent, and on a corpus whose checks are calendar-dependent that comparison
is structurally biased against every prompt candidate, by an amount that grows
one day per day.** It is not the gates malfunctioning — every scenario really
did stop passing — but the cause is the clock, not the bullet. A hand-run on
recording day cannot see this; a scheduled job sees it on night two. **This is
a decision for the owner, not a threshold to move** (§6).

---

## 4. The defect the night found (F-P1-1, fixed)

Attempt 2 ran the whole loop, exited **0**, and did this:

```
turn 1: 2 memory record(s) excluded as belonging to a graph other than 'default'
turn 1: no admissible failure memory: all 2 record(s) came from scenarios of
        another graph, not 'default': no candidate this cycle
stopped: turn 1 produced no candidate
```

`aef loop cycle` calls `resolve_graph_id_from_corpus` and derives the evidence
graph id from the corpus it has already loaded (ADR 0176/0182). **`aef loop
run` never called it at all.** So `evidence_id` stayed the archive-key default
`"default"`, `MemoryEvidence` dropped every record whose run is a
`price-freshness-reviewer` scenario, and the multi-turn driver — the one a
night uses — could not propose on any adopting repo whose graph id is not
literally `default`. Which is every migrated prompt-agent repo.

Reproduced side by side on one repo, one corpus and one memory file, at zero
live cost: `24-run-vs-cycle.txt`. Fixed in `cmd_run`, with
`test_a_run_without_graph_id_no_longer_drops_the_evidence` and a pin that both
turn-running commands settle the question the same way. `GraphIdError` from
`run` is now `EXIT_ERROR` (3), beside `cycle`'s, for ADR 0188's reason.

**This is ADR 0165's shape for the third time**: a pair of commands, one
fixed, the other left, and the difference invisible because the broken one
exits 0. It survived two waves of fixes to its twin. Nothing but leaving the
loop alone would have found it — every previous exercise of this pilot used
`cycle`.

---

## 5. What the halt channel did

**Nothing, correctly.** `21-halt-channel.txt`:

```
--- halt channel log ---
(the channel never fired — no file)
```

There was no halt to report: `13-status.txt` says `kill switch : clear`,
`14-digest.txt` says `Halts: 0`, and two ordinary gate rejections are not halt
criteria. What matters is that the channel was **resolvable** — the same
digest line says

```
- Halt channel configured: yes — /bin/sh (4 argument(s))
```

so had a halt fired there was a command to run, which is precisely the
condition ADR 0195 was written to create and which `aef loop digest` reported
as `NO` before it.

**F-P1-2 (open, not fixed here).** `aef loop doctor` disagrees with `aef loop
digest` about the same repository. `03-doctor-before.txt`:

```
[--] halt channel            none — a halt would tell nobody
     fix: set AEF_HALT_WEBHOOK in your environment (never in this repo)
```

`digest` resolves `halt_channel:` from the base ref through
`loop._halt_channel`; `doctor`'s obligation in `aef/harness/preflight.py` still
checks `AEF_HALT_WEBHOOK`, the environment variable ADR 0195 replaced, and
`doctor` takes no `--config`, so it cannot read the block even in principle.
Two surfaces, one question, opposite answers, and the one an owner is told to
run for a fix is the wrong one. Left for its owner rather than fixed from
here; it changed nothing about the night.

---

## 6. What a person must decide

1. **The live-vs-cassette asymmetry of §3.** Options, none of them free:
   score the incumbent live too (doubles the live cost of every gate and makes
   the incumbent's own score noisy); pin the model's date the way
   `fixed_clock` pins the graph's (a provider change, and it makes the gate
   measure something production will not do); or accept that a corpus with
   calendar-dependent checks has a shelf life and re-record it. **The third is
   the honest default and the first is the tempting one.** Nothing here should
   choose it silently.
2. **Whether the pilot's owner checks should pin day counts at all.** They are
   the owner's, by design (ADR 0113), and they are what makes the failure
   signature real. That they also decay is a property of the checks, not of
   the loop.
3. **Nothing to merge.** Two candidates, both rejected, both archived as
   stepping stones with score 0.0 (`16-lineage.txt`). `master` is untouched
   and `loop/kept` never moved.

---

## 7. What it cost

| | |
|---|---|
| wall clock, the run | 262 s for 2 turns — **131 s/turn**, ~5.5 s per live call |
| live model calls, the night | **48** = 2 turns × (4 candidate + 5 controls × 4) |
| live model calls, the audit | **0** — it is only read when a candidate passes |
| live model calls, the whole increment | **54** of a ≤120 budget (1 preflight + 5 miss probe + 48) |
| corpus passes | 7 per turn (1 candidate + 1 incumbent + 5 controls), 28 scenario executions |
| turns the budget allowed | 2 of 3 — turn 2 started at 131 s, under the 180 s budget; turn 3 did not |

**A note on `--budget-minutes`, since a night is what exposes it.**
`run_loop` checks the wall clock *between* turns, never inside one. So the
budget bounds when a turn may START, not how long the run may last: a 3-minute
budget with a 131-second turn produced a 262-second run, and a turn that took
an hour would take an hour. That is why `night.sh` carries its own `alarm`.
Worth saying out loud; not fixed here.

---

## 8. What this night does and does not establish

**Does.** The loop has now closed unattended once, on a third-party-shaped
repo, with live model calls, a real halt channel, a memory file the harvest
step reads, and a base branch that is not `main`. It proposed from harvested
production evidence, gated with six gates, rejected both candidates, stopped
on its own rule, kept nothing, moved nothing, and left a ledger, a lineage, a
journal and a digest a person could read cold. **And it found a defect that
made the command it ran incapable of proposing at all** — which is the
strongest possible argument for the exercise.

**Does not.** One night is one night. Nothing was kept, so the audit slice was
never actually read against a passing candidate — the comparison exists, is
tested, and has not yet had an occasion. `--candidates 2` was configured and
never had a second candidate to try. Nothing here is ~100 runs a night; it is
two turns in four minutes, and the honest gap between those numbers is the
proposer's repertoire, not the driver.
