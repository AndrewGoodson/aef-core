# Loop prompt — does aef-core fit Raptor's alpha-hunt floor?

Paste after `/loop`.

---

LOOP_PROMPT — test whether aef-core adds anything measurable to Raptor's
Research Floor. **The answer may be no. That is a result, not a failure.**

## What already got settled, so you do not re-derive it

An earlier pass concluded *do not adopt aef-core into Raptor's Python layer*,
and that conclusion stands and is not what this loop revisits. Its basis:
Raptor already has multi-backend LLM fallback, gates, an audit journal, five
replay modules, 2,158 test files, and a learning-file convention. `aef migrate`
found the entire wrappable Python surface — **2 call sites, plus 1 async one it
cannot take.**

What that pass did NOT evaluate is the thing Raptor actually runs: the
**alpha-hunt floor** — seven markdown-defined Claude Code subagents sequenced by
`head-of-research` (InGen) through an 8-step round. This loop evaluates that,
and only that.

Also settled, do not spend a round rediscovering it: **Raptor's enforcement is
server-side and is better placed than AEF's.** Write routes are allowlisted, the
campaign is server-pinned, honest-N is a server-computed manifest read-only to
the floor, the shadow roster is firewalled, and promotion is fenced at human F7.
An agent cannot reach around an HTTP boundary. AEF's equivalent lives in a
library the candidate can import — that is aef-core ADR 0109's whole finding.
**Any proposal that moves enforcement from the server into a library is wrong by
construction and must be rejected, not evaluated.**

## The four hypotheses. One per iteration. Each must be falsifiable.

For each: state what you expect, construct the case, RUN it, and record the
measurement. An argument is not evidence. If a hypothesis dies, say so and move
on — the loop's value is the ones that survive contact.

**H1 — the round has no replay.** InGen sequences seven seats by reading
markdown. `raptor_run_log_write` stores free-form `content` keyed by
session_id/team/agent_seat/phase — a log, not a trace. A grep for
`round_trace|replay_round|floor_trace` returns nothing. So: can a completed
round be re-executed and asserted identical? If a verdict is disputed, what
reconstructs how it was reached? AEF has `GraphExecutor` + checkpoint/replay +
provenance. *Test:* take the round that just ran, and try to reconstruct it from
what the system retained. Name precisely what is missing.

**H2 — the caps are self-enforced.** Round cap 5, re-work ≤3, repair ≤2 are
numbers in `head-of-research.md`, counted by the agent they constrain. aef-core
ADR 0094's finding is that a child reporting its own results forges them as
before; what works is the parent owning state and step count. *Test:* can InGen
exceed a cap with nothing catching it? Construct the case — do NOT run a real
round to do it. Then establish the blast radius honestly: every consequential
path is server-fenced, so the question is whether exceeding a cap corrupts
anything or merely wastes compute.

**H3 — no regression suite for the floor.** Raptor's 2,158 tests cover Python.
What catches a behavioural regression when a *seat prompt* changes? *Test:* is
there any artifact asserting "this hypothesis, through this floor, still reaches
this disposition"? If not, that is exactly what AEF's eval harness plus a golden
corpus is for — and it is the highest-value candidate in this list, because it
needs no change to how the floor runs.

**H4 — seat handoffs are conventional, not enforced.** Scout hands Sequence a
hypothesis slate; Sequence hands Splice a `blueprint_id`. *Test:* what happens
when a seat returns a malformed handoff? Is it caught, or does the round
continue on a bad value? Compare with AEF's typed `StateDelta`.

## Where AEF could attach, if anywhere

Only two shapes are worth proposing. Anything else, reject:

- **Wrap the round for trace/replay/checkpoint only** — seats stay prompts,
  AEF observes. Additive.
- **Golden corpus + eval harness over floor dispositions** — catches prompt
  regressions. Additive, and touches nothing at runtime.

**Rebuilding the seats as AEF nodes is not on the table.** It would trade an
LLM-orchestrated floor that works for a rigid graph, and would move enforcement
toward the agent. Do not propose it.

## Hard limits

- **Do NOT run another alpha hunt without asking.** A round consumes honest-N
  budget against the live manifest and submits real blueprints. One is already
  running; use its output as evidence.
- **Do NOT modify any file under `plugins/prop-firm/agents/` or
  `.claude/agents/`.** Those are the live floor. Propose changes; do not make
  them.
- **Do NOT touch** `daemon/`, `daemon_v2/`, `cron/`, `state/`, `logs/`. The
  daemon is now running (pid 60781); leave it alone.
- **Never `git add -A`** — Raptor's tree has ~251 uncommitted entries including
  live scheduler state. Stage explicit paths and check `git status --short`
  before every commit.
- **Never commit to Raptor's `main`.** Work on `aef/integration-phase0`.
- Tier-1 auto-merge stays off; `aef/evolution/` stays disabled.

## Each iteration

1. Orient: confirm branch, re-read this file and the hypothesis you are on.
2. Take the earliest untested hypothesis. State what you expect BEFORE testing.
3. Construct the case and run it. Read the output; an exit code is not evidence.
4. Record in `AEF_FLOOR_FIT_FINDINGS.md`: hypothesis, expectation, what you ran,
   the measurement, and a verdict of CONFIRMED / FALSIFIED / UNPROVABLE-HERE.
5. Commit explicit paths. Report in ≤10 lines and STOP. One hypothesis per run.

## Done

When all four are tested, write a recommendation: **integrate / integrate-narrowly
/ do-not-integrate**, with the evidence per hypothesis and the residual risk
stated plainly.

If the answer is do-not-integrate, say it in one sentence and do not soften it.
Two passes have now concluded AEF adds little to Raptor; a third saying the same
thing with evidence is worth more than a forced integration. The useful output of
this loop may be a precise list of what Raptor's floor lacks — replay, a floor
regression suite, externally-owned caps — which Raptor can then build **natively,
server-side, without AEF**. That is a legitimate and probably better outcome.
