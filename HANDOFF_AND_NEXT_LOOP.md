# Handoff — state as of 2026-08-10, and the next loop

Self-contained. Assumes no memory of prior sessions.

---

## Part 1 — where things stand

### Two repos, two different conclusions

**`/Users/raptor/aef-core`** — a Python runtime for agent graphs (kernel,
checkpoint/replay, deny-by-default policy engine, memory, OTel, eval harness,
loop harness). 1455 tests, mypy strict clean, ruff clean. Plus `mindgraph/`,
an offline dashboard artifact (287 verifier checks).

**`/Users/raptor/Raptor`** — a live prop-firm trading system. 6,259 Python
files, 2,158 test files, a running daemon and API, and the **alpha-hunt
Research Floor**: seven markdown-defined Claude Code subagents sequenced by
`head-of-research` (InGen) through an 8-step round.

### Settled: do NOT adopt aef-core into Raptor

Three independent passes reached this, the last with a live experiment behind
it. Do not reopen without new evidence.

1. Raptor already has everything AEF offers, usually better suited: multi-backend
   LLM fallback, gates, an audit journal, five replay modules, a learning-file
   convention.
2. `aef migrate` found Raptor's entire wrappable Python surface: **2 call sites,
   plus 1 async one it cannot take.**
3. Raptor's agents are **markdown prompts**, not Python — AEF's node contract has
   nothing to attach to at the agent layer.
4. **Decisive:** Raptor's enforcement is server-side (write allowlist, campaign
   pinning, server-computed honest-N, roster firewall, promotion fenced at human
   F7). AEF's lives in a library the candidate can import — that is aef-core
   ADR 0109's finding. **Any proposal moving enforcement from Raptor's server
   into a library is wrong by construction.**
5. A live round found seven defects. **AEF would have prevented none of the six
   that matter.**

aef-core is fine; it just needs an adopter that is *starting* an agent system,
not one that is finished.

### Done: the supervised alpha-hunt round (2026-08-06)

One round, operator-supervised. All 12 blueprints returned **0 trades** — the
idea was never tested, and the system mislabelled the empty runs as `MERIT`
("tested, no edge"). Honest-N stayed virgin, so nothing was poisoned.

Also proved `raptor_daemon_health` is a **lagging projection**, not liveness: it
reported `down` while the fleet screened blueprints in ~46s.

### Done: the floor-fix loop — all 7 increments, merged to Raptor `main`

Raptor `main` is at `6bfa6acd0`. Fixed:

- **P0b** signed-distance mirror bug — 30 signed columns now sign-reflect the
  threshold on operator complement; 3 side-neutral columns carry unflipped.
  (`scripts/hunt_flip_util.py`)
- **P1a** zero-trade runs no longer report `MERIT`; new `ZERO_TRADE` bucket.
- **P2a** new `GET /api/manifest/column-occupancy`. On the real artifact,
  **90 of 321 flag columns never fire once** — the instrument that would have
  caught round 1's waste before it ran.
- **P2b** oversized manifests paginated; read-only seats can consume them now.

### OPEN — two are owner calls, not engineering

1. **P0a: 7,010 already-banked mirror blueprints (12.1% of all `_FLIP`, 99.9%
   already screened) tested the wrong opposite side** before the P0b fix.
   Whether that invalidates specific prior conclusions is **your call.**
2. **P1b / VOL-3521: the unauthorised auto-mint.** Round 1 authorised 8
   blueprints; 12 landed. `factory/auto_invert.py` mints unconditionally.
   Genuinely ambiguous whether it is an intended successor or an orphan nobody
   disabled. Both dispositions scoped in the ticket; neither implemented.
   **Your call.**
3. **VOL-3519**: P0b's residual gaps (2 signed columns shadowed by the fix).
4. **The OHLCV closure** — the review seat ruled the round-1 hypothesis should
   never have been authorised under the standing closure, but noted its
   rationale does not transfer to a *location* feature, and 48 volume-profile
   columns have never been screened. Affirm the broad closure, or narrow it and
   grant a scoped exception. **Your call.**

### What the floor still lacks — the real next work

None of these needs aef-core. All three belong **server-side in the hub**,
where the floor cannot forge them.

- **Round replay** — no way to re-run a round's request sequence under a
  different auth posture. P3 had to reconstruct it by reading code.
- **A regression suite for seat behaviour** — nothing pins "a floor token sees
  the opaque roster, not the full one" as an executable test.
- **Externally-owned round caps** — the 8-authorised/12-landed gap was only
  visible because someone counted afterward.

### Watch item

Daemon is GREEN (heartbeat refreshing) but **`cycles=0` after ~34 hours
uptime**. Either genuinely idle with nothing queued, or it has never completed a
work cycle. Worth confirming before trusting it to process a round.

---

## Part 2 — the next loop

Paste after `/loop`.

---

LOOP_PROMPT — build what the alpha-hunt floor lacks, server-side.

Repo: `/Users/raptor/Raptor`. Read `HANDOFF_AND_NEXT_LOOP.md` in
`/Users/raptor/aef-core` first — it is the full state and you have no memory of
how any of this was decided.

**Create your own branch off `main`** (`git checkout main && git checkout -b
floor/observability`). Raptor has other branches in flight (`raptor-fix`,
`codex/*`) — do not touch them.

### The four rules that outrank the work

1. **NEVER `git add -A`.** ~271 uncommitted entries including live scheduler
   state. Stage explicit paths; run `git status --short` before every commit.
2. **Never commit to `main`.** No PR, no merge, no force-push.
3. **Never touch `daemon/`, `daemon_v2/`, `cron/`, `state/`, `logs/`.** The
   daemon and the API on `127.0.0.1:8001` are LIVE. Restarting either is an
   operator action — if a change needs a restart, say so and stop.
4. **Do NOT run an alpha hunt.** A round consumes honest-N against the live
   manifest and submits real blueprints. Everything below is unit-testable.

**This changes live pipeline behaviour.** Reproduce first: write the failing
test, watch it fail for the right reason, fix, watch it pass. A fix without a
test that fails without it is not done.

### Do not "fix" these — they are correct

- `factory/signal_flip.py::invert_blueprint_direction` swaps
  `entry_long`/`entry_short`. Sound. **Not** the mirror bug (that was P0b, fixed).
- Raptor's server-side enforcement. Do not move any control toward the agent.

### Increments, one per iteration

**1 — confirm the daemon actually cycles.** `cycles=0` after ~34h uptime with a
live heartbeat. Determine whether that is idle-normal or a stall, from logs and
the lock file — **without restarting anything**. If it is a stall, report and
stop; that outranks everything below.

**2 — the auth-tiering regression suite.** `tests/unit/`, pure-function style,
mirroring the P1a/P2a/P2b tests already on `main`. Pin, as executable tests:
a floor token sees the opaque roster projection and not book-mapping; a
write-gated route 401s a floor token with no write scope; the loopback bypass
(`api/auth.py:155`) is exercised deliberately rather than by accident. Round 1
ran entirely unauthenticated over loopback, so **the floor's real security
posture has never been executed even once.**

**3 — round accounting as a first-class artifact.** Server-side: N authorised,
M landed, delta attributed. The 8-vs-12 gap was only caught by hand. This is
reporting, not enforcement — do not add a blocking cap without an owner call.

**4 — round replay.** Record a round's request sequence so it can be re-run
under a different auth posture. Build it in the hub — a trace the floor writes
about itself is forgeable; one the hub writes is not.

### Green bar, before and after every increment

```
pytest tests/unit/ -m "not slow and not nightly and not engine" -q
```
Scope to what you changed plus `tests/unit/`. Raptor's CI runs mypy non-blocking
(`|| true`, VOL-208) — hold new code stricter than the tree around it.

### Each iteration

Orient (branch, `git status --short`, re-read this file) → take the earliest
unfinished increment → state your expectation before testing → write the failing
test and run it → fix → green bar → append to `FLOOR_OBS_LOG.md` with the
transcript → commit explicit paths → report ≤10 lines → **STOP.** One increment
per run.

### Escalate rather than proceed if

A change would require restarting the API or daemon; would modify anything under
`plugins/prop-firm/agents/` or `.claude/agents/` (the live floor — propose, do
not edit); or would require committing files you did not create.

### Do not do

Do not implement the four owner decisions in Part 1 (P0a remediation, VOL-3521
auto-mint disposition, VOL-3519, the OHLCV closure). Surface them; they are not
yours to settle.
