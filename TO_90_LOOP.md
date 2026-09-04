# To-90 loop — the last six points

Input: the rubric (`docs/research/self-learning-rubric.md`) and the report
`docs/research/above-90-2026-09-04.md`. Output: 90/100, or an honest
statement of which points are owner decisions and remain unclaimed.

Every rule of `IMPROVE_LOOP.md` applies unchanged; the multi-agent protocol
of `ABOVE_90_LOOP.md` applies unchanged (orchestrator owns `main`, workers
commit on branches in isolated worktrees, seam-hunt after each merge wave).
Read `CLAUDE.md` first. HARD-STOP gates
(`docs/autonomy/self-improving-loop.md` §4) bind.

## The arithmetic, corrected

I0 (below) corrects a one-point error that ran through every total since
the baseline. **After I0 the score is 85**, and the remaining five points
are:

| Dim | Now | Target | What it needs | Blocked on |
|---|---|---|---|---|
| 2 | 17 | 19 | I12 — the ACE four-arm measurement | quota |
| 1 | 19 | 20 | I13 — the live noise floor | quota |
| 3 | 8 | 9 | I14 — judge A/B with the answer in evidence | quota |
| 8 | 4 | 5 | I15 — Codex CLI smoke | owner (one command) |

85 + 2 + 1 + 1 + 1 = **90**, without touching dimension 7. Dimension 7's
five points (a real tenant) and dimension 4's last point (containment on by
default) stay unclaimed and stay honest.

**Do not manufacture points.** If a measurement does not move, the score
does not move and that is the result — the rule that has already killed
four knobs in this programme.

## I0 — the rubric's arithmetic is under test (dim: none; ADR 0127)

**Reproduce, RUN.** Parse the rubric's "Current" table, take the most
recent row per dimension, and carry the dimensions that never moved (4 and
8) from the baseline: **85**. The heading says 84. Walk it back: the
baseline's own rows sum to 51 against a stated 50, and every increment
since did delta arithmetic from the wrong base.

**Change.** Correct the heading and every intermediate total in the file's
history section, each with a one-line note that it is a correction, not a
re-scoring — no dimension's evidence changes. Add
`tests/test_rubric_arithmetic.py`: the latest row per dimension sums to the
heading; every dimension in the weights table appears; no score exceeds its
weight. **Mutation-check it**: perturb the heading by one, see it fail.

**Why it is an increment and not a chore.** The rubric's own first rule is
that a score moves only on an artifact. A total nothing recomputes is a
number nobody checked — the defect class this repo keeps finding, applied
to its own scoreboard.

## Quota preflight — before any live increment

The `claude -p` quota is exhausted as of 2026-09-04 and is what stopped
I12, I13 and I14. **First action of any live increment:**

```
claude -p --no-session-persistence --output-format json --max-turns 1 \
  --tools "" --strict-mcp-config --mcp-config {} --safe-mode \
  --model <model> "Reply with the single word OK"
```

Read `is_error`, `result`, and `usage.input_tokens`. Three outcomes:

- **OK, input tokens ≲ 10k** — proceed; record the token count, because ADR
  0126 changed the argv to cut it from ~211k and nobody has measured the
  fix.
- **OK, input tokens ≫ 10k** — the isolation flags are not working. Stop,
  report, do not spend the budget on a measurement whose per-call cost is
  40× what the ADR claims.
- **rate limit / not logged in** — stop. Report "quota unavailable" and run
  the no-quota lane below instead. Do not switch models silently: I3's,
  I10's and I11's numbers were measured on `claude-fable-5-1`, and a
  comparison across models is not a comparison. If the owner authorises a
  different model, say so in the ADR and re-measure the baseline arm too.

Budget every increment in calls before starting, and report calls made.

## I12 — the ACE measurement on the task metric (dim 2: 17 → 19; ADR 0128)

The runner exists and is dry-run verified:
`<scratchpad>/i12_ace_arms.py`, **42 calls at `--repeats 1`**. Copy it into
the worktree's `.scratch/` and run it there.

Four arms over the summary corpus's validation split (6 scenarios, all
`graph_id == "summary_agent"`), each with fresh stores so no arm inherits
another's experience: (a) no retrieve node, (b) retrieve, raw records only,
(c) retrieve + knowledge layer, (d) (c) + `reflection.impl: llm`.

**Falsification, stated before running:** if (c) ≤ (b) the knowledge layer
buys nothing on a task metric, dim 2 does not move, and ADR 0110's coverage
result is demoted to a proxy that does not predict task outcome — say so.
If (d) ≤ (c) the LLM reflection stays off. **A gain smaller than the spread
is not a gain**, so `--repeats 2` minimum (84 calls) if the budget allows;
at `--repeats 1` the spread is unknown and the claim must say so.

Deliverable: ADR 0128 with the four-arm table, the spread, calls made, and
whichever falsification fired; rubric row; `IMPROVE_LOG.md` entry.

## I13 — the live noise floor (dim 1: 19 → 20; ADR 0129)

I11 left this undone after three timed-out attempts. Two parts:

1. **The floor.** Score the summary corpus's validation split with
   `cassette_miss="live"` at `--repeat 3` (18 calls) and report the spread
   of the mean. This is the number every future live claim must clear.
2. **The planted regression.** Remove the must-mention instruction from the
   draft prompt, score live (18 calls), confirm the score falls by more
   than the floor, revert, prove the revert with a diff against a backup.

**Run each score in the foreground with a 600 s tool timeout**, one repeat
at a time, writing each repeat's result to `.scratch/` as it completes — I11
lost three runs to all-or-nothing invocations. If a single repeat exceeds
600 s, report the throttle and claim nothing.

## I14 — the judge, now that it can read the answer (dim 3: 8 → 9; ADR 0130)

ADR 0126 put `working_memory` into `_evidence`; the measured 3/18 and 9/18
agreements predate it. Re-run I11's A/B on the 18 summary states (36
calls): rule-based vs LLM agreement with the owner checks, and the
position-swap delta. Dim 3 moves only if the LLM judge now agrees with the
checks materially more often than the rule-based one **and** the position
delta stays small. If the LLM judge improved because it can now see the
answer, that is the finding; if it did not, say that instead.

## I15 — the Codex path (dim 8: 4 → 5; owner + ADR 0131)

Owner action, one command: `npm i -g @openai/codex@latest`. Then a worker
runs the smoke recorded in `docs/model-checks/2026-09-03-claude-fable-5-1.md`
against `CodexProvider` and, if it answers, converts ADR 0112's "not
reproduced — the adapter's parsing is a hypothesis" into a measurement and
adds a live-path test marked so CI skips it without the CLI. If Codex still
cannot parse its catalogue, dim 8 stays 4 and the ADR says why.

## No-quota lane — what to do if the preflight fails

Only one point is reachable without live calls, and it is a control
question rather than a capability:

**Dim 4 (14 → 15): shadow containment is opt-in.** ADR 0105 built the
contained shadow and left it opt-in; the trust case's second finding is
that a shadow node doing direct file I/O is not contained by the tool
policy. Making the container the default **when an image is available**,
falling back with a named warning when it is not, strengthens a control and
is therefore allowed without an owner decision — but it is promotion-path
code, so: reproduce the uncontained case first, keep the fallback explicit
and logged, and do not touch `PolicyEngine`, the gates, or Tier-1. If the
change cannot be made without weakening anything, stop and ask (HARD-STOP
gate 2).

That takes the score to 86 and no further. **Do not fill the remaining four
points with anything else.** Report them as blocked and stop — a loop that
manufactures work when its inputs are unavailable is the failure mode
§7 of the autonomy contract exists to prevent.

## Owner actions this loop cannot take

- `npm i -g @openai/codex@latest` (I15's precondition) — dim 8, +1.
- Point `harvest` at a real tenant's runs — dim 7, up to +5. ADR 0119 made
  it safe; fix wave B made it work; nobody has done it, and the trust case
  names it as the criterion that has never run. **This is the only path
  past 90**, and it is a decision, not an increment.

## Report

`docs/research/to-90-<date>.md`: the rubric re-scored with the corrected
arithmetic, every measured number, every falsification that fired, calls
made per increment, and the owner actions still outstanding. Then stop.
