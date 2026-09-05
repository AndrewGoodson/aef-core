# ADR 0156: The live noise floor, and a planted regression that hides under it

## Status
Accepted. Increment S2 of `UPGRADE_LOOP.md` (= I13 of `TO_90_LOOP.md`).
**Dimension 1 does not move. It stays 19/20.** The falsification stated
before the run fired.

## Model

Every number below was measured on the session default, **`claude-opus-5`
(reported by the CLI as `claude-opus-5[1m]`)**, on 2026-09-04. ADR 0123's
cassette was recorded on `claude-fable-5-1`, whose quota is exhausted; a
comparison across models is not a comparison, so the incumbent arm was
re-measured live on Opus rather than compared against the fable recording.

## Quota preflight (ADR 0150's corrected argv)

```
claude -p --no-session-persistence --output-format json --max-turns 1 \
  --tools "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --safe-mode "Reply with the single word OK"
```

`is_error: false`, `result: "OK"`, **`usage.input_tokens: 2`** (plus 3,334
cache-creation tokens), `modelUsage` naming `claude-opus-5[1m]`. Isolation
is working and the quota is available — the first live increment since the
exhaustion that stopped I12/I13/I14. Raw JSON:
`docs/research/i13/preflight.json`.

## Context

I11 (ADR 0123) left the live noise floor unmeasured after three attempts
each ran past a ten-minute wall. Its ADR recorded that as a throttle and
claimed nothing, which was the honest call on the evidence it had. The
evidence was wrong about the cause.

## Two defects found before any number could be produced

### D1 — `--cassette-miss live` on the incumbent makes **zero** live calls

`TO_90_LOOP.md` §I13 asks for the floor by scoring the validation split at
`--repeat 3 --cassette-miss live`, and budgets **18 calls** for it. Run as
written, it makes **none**:

```
$ aef loop score agents.summary.graph:build_graph --corpus corpus \
    --splits validation --repeat 1 --cassette-miss fail --config <cfg>
  model calls: 6 cassette hit(s), 0 miss(es), on_miss=fail — replayed
  validation  n=6 with_checks=6 mean=0.9167 stdev=0.1291 repeat_spread=0.000000
```

The incumbent prompt reproduces the recorded request byte-for-byte, so the
cassette key matches and `CassetteProvider` serves the hit without touching
the inner provider — by design (ADR 0123). `on_miss` only governs misses.
A "live floor" collected that way is the *replayed* floor: `repeat_spread
0.000000`, three times over, with the model never asked anything.

This is a defect in the increment's specification, not in the code. It is
recorded here because the same sentence appears in `UPGRADE_LOOP.md` M2 and
M5 ("every gate pass of a prompt candidate is live"), and there the premise
holds — a *changed* prompt misses. It is only the incumbent arm that
silently replays.

**Method taken.** The floor arm scores a scratch copy of the corpus with the
six summary validation scenarios' `model_calls` emptied, so every draft call
misses and goes live. The regression arm scores the *same* copy, so the only
difference between the arms is the prompt. Script:
`docs/research/i13/strip_cassettes.py`. The repo's `corpus/` is never
written to.

### D2 — the corpus's word-cap check is a ReDoS, and it is what stopped I11

With the cassettes emptied, the first live run hung. `faulthandler` past a
45-second wall put the stack here, not in the model call:

```
File "aef/harness/checks.py", line 134 in _holds
File "aef/harness/checks.py", line 111 in evaluate_checks
File "aef/harness/evaluation.py", line 110 in score_scenario
File "aef/harness/scenario_runner.py", line 209 in run_scenario
```

Every summary scenario carries an owner check
`{"op": "regex", "path": "working_memory.summary", "value":
"^(?:\\s*\\S+){1,N}\\s*$"}` — a word cap. A nested quantifier over an
ambiguous inner group: `\s*` may match empty, so `\S+` may be split at any
position, and the number of ways to cut a k-character string into ≤ N
non-space runs is exponential in k. A **match** short-circuits on the first
greedy path. A **failure** must exhaust every one of them.
`aef/harness/checks.py::_holds` calls `re.search` with no timeout.

Reproduced (`docs/research/i13/redos_repro.py`), each pattern run in a child
process with a 20-second wall:

| input | words | corpus pattern | linear equivalent |
|---|---|---|---|
| the fable recording's answer for `sum-13` | 35 | match=True in **0.05 ms** | match=True in 0.05 ms |
| an Opus answer for `sum-13` | 36 | **DID NOT TERMINATE in 20 s** | match=False in 0.06 ms |

One word over the cap is the difference between 0.05 ms and never. So the
scorer hangs on exactly the input a live model produces when it overruns —
which is the *only* input this check exists to catch. **This is why I11's
three live attempts each ran past ten minutes**, and why they were
attributed to a throttle: nothing in the harness reports where a score is
spending its time, and the model call is the plausible suspect.

The recorded cassettes all sit at or under the cap, so the replayed path
never touches the failing branch. The defect is unreachable from every
green test in the repo and reachable from every live gate pass.

**Not fixed here.** `aef/harness/checks.py` and `corpus/` are outside this
worker's file list. Reported for routing; the fix is two independent
changes (a bounded matcher in `_holds`, and a linear pattern in the corpus)
and either alone closes it.

**Method taken.** Both arms score a scratch copy in which the word cap is
rewritten to the linear-time equivalent
`^\s*\S+(?:\s+\S+){0,N-1}\s*$`. The two patterns denote the same predicate
— *the whitespace-separated token count is between 1 and N* — because the
minimal decomposition of a string into non-space runs is its token list.
Equivalence is asserted two ways
(`docs/research/i13/linearise.py`):

1. 4,000 generated strings per cap (30/35/40), varying token count, token
   content, separator width and leading/trailing space, restricted to the
   region where the original terminates. Zero disagreements.
2. **The whole replayed metric is byte-identical**: scoring the rewritten
   corpus with cassettes intact reproduces ADR 0123's numbers exactly —
   train `0.9792`, validation `0.9167`, and every per-scenario score
   unchanged, including all three of the `0.75` content failures.

## The floor

Six scenarios (the summary corpus's validation split, all
`graph_id == "summary_agent"`), one repeat per invocation, three
invocations, each in the foreground under a 600 s wall, each written to
scratch as it completed. Cassette: `0 hits, 6 misses, on_miss=live` on
every repeat — every score below is LIVE.

| repeat | mean | stdev | cost tokens | sum-13 | sum-14 | sum-15 | sum-16 | sum-17 | sum-18 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.8333 | 0.2041 | 462 | 0.75 | 0.50 | 1.00 | 0.75 | 1.00 | 1.00 |
| 2 | 0.7917 | 0.1882 | 468 | 0.75 | 0.50 | 1.00 | 0.75 | 0.75 | 1.00 |
| 3 | 0.6667 | 0.3764 | 370 | **0.00** | 0.50 | 1.00 | 0.75 | 0.75 | 1.00 |

mean of means **0.7639** · spread (max − min) **0.1666** · stdev of the
means **0.0867**.

> **floor (Opus, 2026-09-04): mean 0.7639, spread 0.1666 over 3 repeats of 6 scenarios**

That is the line every future live claim on this suite has to clear, and it
is the bar M4/M5/M6 use for prompt candidates.

**On repeat 3's `0.00`.** Established without spending a call
(`docs/research/i13/zero_signature.py`): both a provider that raises and a
provider that returns `""` produce exactly
`score=0.0000, cost_tokens=0` for this scenario. Repeat 3's split cost is
370 tokens against ~465 for the other two — one call's worth missing. So
the `0.00` is a **harness/model failure, not a content failure**: a summary
of any length would pass at least the word-cap check. A third of the floor's
spread is therefore transient live-call failure rather than model variance,
and that is a property of live scoring, not an artefact to be excluded — a
gate pass will meet it too.

**A reporting gap this exposed.** `aef loop score --json` emits per-scenario
scores and a cassette hit/miss count, but neither the per-scenario `failure`
string nor the check failures that `run_scenario` already computes. A 0.0000
that means "the provider died" and a 0.0000 that means "the answer was
wrong" are indistinguishable in the report, and telling them apart above
required inferring from token accounting. Reported, not fixed
(`aef/cli/loop.py` is outside this worker's files).

## The planted regression

`agents/summary/graph.py::draft_prompt` builds the user turn. The
must-mention instruction — the sentence that names the terms the `contains`
checks look for — was removed, leaving:

```
Summarise the passage below in at most 35 words.

Passage:
<text>
```

Same corpus copy, same config, same model, three repeats, one per
invocation.

| repeat | mean | stdev | cost tokens | sum-13 | sum-14 | sum-15 | sum-16 | sum-17 | sum-18 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.7083 | 0.2923 | 480 | 0.75 | 0.25 | 1.00 | 1.00 | 0.50 | 0.75 |
| 2 | 0.7500 | 0.2236 | 474 | 0.75 | 0.50 | 1.00 | 1.00 | 0.50 | 0.75 |
| 3 | 0.7500 | 0.2236 | 485 | 1.00 | 0.50 | 1.00 | 0.75 | 0.50 | 0.75 |

mean of means **0.7361** · spread **0.0417** · stdev **0.0241**.

## The verdict

| quantity | value |
|---|---|
| floor, mean of means | 0.7639 |
| regression, mean of means | 0.7361 |
| **fall** | **0.0278** |
| floor spread (max − min) | 0.1666 |
| floor stdev of the means | 0.0867 |
| fall ÷ floor stdev | 0.32 |
| every regression repeat vs every floor repeat | **overlapping** (floor min 0.6667 < regression max 0.7500) |

**The regression is six times smaller than the noise it has to be seen
against.** The falsification stated before the run — *"the score must fall
by MORE than the floor's spread for dim 1 to move; if it falls by less, the
harness cannot detect a regression of that size live and dim 1 does not
move"* — fired. **Dimension 1 stays 19/20.**

Two things this does *not* say:

- It does not say the regression is harmless. Under the cassette it is
  catastrophic and unmistakable: ADR 0123 measured **0.0000 with 36 misses
  and no live call**, because a changed prompt is a *behavioural* difference
  the default `on_miss="fail"` reports rather than answers. The replayed
  path detects this regression perfectly. The live path does not detect it
  at all.
- It does not say the prompt instruction is useless. Per scenario the
  removal is not uniform: `sum-17` fell in all three repeats (1.00/0.75/0.75
  → 0.50/0.50/0.50) and `sum-18` in all three (1.00 → 0.75), while `sum-16`
  *rose* in two (0.75 → 1.00). The instruction moves individual scenarios;
  six scenarios are not enough for the mean to resolve it.

The mechanism is visible in the passages themselves. The must-mention terms
are the subject of the text — "Dunmere cider press", "oak", "apples" — so a
competent unprompted summary names most of them anyway. The instruction buys
the last term, not the summary, and a per-check metric over six scenarios
averages that away.

## Consequences

1. **The floor is the number, and the number is large.** 0.7639 ± 0.1666 on
   six scenarios. A live gate pass on this suite can only see a change worth
   more than about 17 points of the mean — one whole scenario going from
   right to wrong, consistently, in every repeat. `UPGRADE_LOOP.md`'s M4/M5
   should read the bar as: **on this corpus, a live-gated prompt candidate
   cannot be accepted or rejected on the mean alone.**
2. **The corpus is the binding constraint, not the harness.** Six scenarios
   with four checks each gives 24 binary outcomes, of which live variance
   already moves two to four. The cheapest route to a usable live floor is
   more scenarios, not a better scorer — the spread falls as 1/√n, so
   roughly 40 scenarios would put it near 0.06.
3. **Per-scenario, paired comparison beats the mean.** Both arms scored the
   same six scenarios; `sum-17` and `sum-18` fell in 3 of 3 repeats and
   nothing rose in 3 of 3. A sign test over paired scenarios would have
   flagged the regression where the mean could not. This is a change to how
   a live comparison is *read*, and it is not made here — it is offered to
   the S-thread with the data to support it.
4. **D2 blocks every live measurement in this repo until it is fixed.** Any
   live run whose model overruns a word cap hangs indefinitely and is
   currently indistinguishable from a slow model. It cost I11 three runs and
   cost this increment four.

## Calls made

| purpose | calls |
|---|---|
| quota preflight | 1 |
| diagnostic — reproducing D1/D2 (one timed-out `loop score`, two timed-out single-scenario runs, one direct provider latency probe) | 4 |
| floor, 3 repeats × 6 scenarios | 18 |
| planted regression, 3 repeats × 6 scenarios | 18 |
| **total** | **41** |

The measurement budget was 36 and 36 were spent on measurement. The four
diagnostic calls are over the stated budget and are reported rather than
folded into it.

## Restore proof

`agents/summary/graph.py` was copied to the worker's scratch before the
edit and restored from that copy afterwards.

```
before  5d91590952cb54ef9bf72bdc94838942092a0b55e0f689f88bc3e34acfede885  agents/summary/graph.py
        5d91590952cb54ef9bf72bdc94838942092a0b55e0f689f88bc3e34acfede885  graph.py.backup
after   5d91590952cb54ef9bf72bdc94838942092a0b55e0f689f88bc3e34acfede885  agents/summary/graph.py
        5d91590952cb54ef9bf72bdc94838942092a0b55e0f689f88bc3e34acfede885  graph.py.backup
$ git diff --exit-code agents/summary/graph.py; echo $?
0
```

## A third defect, reported not fixed

`ClaudeCodeProvider.complete` attributes the answer with
`answered_by = next(iter(model_usage), None)`. The CLI's `modelUsage` map
carries the harness's own auxiliary calls alongside the one that answered,
and on this machine it is ordered `claude-haiku-4-5-20251001` first,
`claude-opus-5[1m]` second. So a call issued with `--model claude-opus-5`
returns `CompletionResult.model == "claude-haiku-4-5-20251001"`, and that
string is what `Provenance.model` records for every node and what a future
recording pins. Measured directly: one provider call with the sum-13 draft
request, `--model claude-opus-5` in argv, `model=claude-haiku-4-5-20251001`
out. Dictionary insertion order is not a model attribution.
`aef/providers/harness_provider.py` is outside this worker's files.

## Evidence

- `docs/research/i13/preflight.json` — the quota preflight, raw.
- `docs/research/i13/floor-r{1,2,3}.json` — the three floor repeats, raw
  `aef loop score --json` output.
- `docs/research/i13/regress-r{1,2,3}.json` — the three regression repeats.
- `docs/research/i13/redos_repro.py` — D2, runnable, 20-second wall.
- `docs/research/i13/linearise.py` — the linear rewrite and its equivalence
  check.
- `docs/research/i13/strip_cassettes.py` — the cassette emptying that makes
  the incumbent arm live.
- `docs/research/i13/zero_signature.py` — what a 0.0000 with zero cost
  tokens means, established with stub providers and no live call.
- `docs/research/i13/aef.measurement.yaml` — the config both arms used.

## Confidence

High that the floor is the floor for this corpus under this model: three
repeats, every one live and reported as such, both arms on identical inputs
with one prompt line between them.

High on D2 — reproduced from a stack trace, then in isolation, then closed
by a rewrite that reproduces the entire replayed metric byte-for-byte.

Medium on the *cause* of repeat 3's `0.00`: the signature and the token
accounting both point at a failed call, but the harness does not report
which, and the run cannot be replayed to find out.

Low on generalisation. Six scenarios of one shape, one night, one model.
The claim that a 0.028 regression is undetectable is a claim about **this**
corpus's resolution, and consequence 2 says what would change it.

## Note (orchestrator, at merge)

Written against the pre-J0 rubric: dim 1 was 19/20 on this branch and is **15/20** on `main` after ADR 0151. The delta claimed here is 0 either way, so no row moves; the floor line and the ReDoS finding stand unchanged.
