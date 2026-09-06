# To-95 loop — leave it running, and prove the second lesson

Input: 78/100 (an outside reviewer's number, ADR 0188 plus the increments
after it). Output: whatever the rows sum to, and an honest statement of what
only a second person can buy.

Every rule of `IMPROVE_LOOP.md` and the multi-agent protocol of
`ABOVE_90_LOOP.md` apply unchanged. HARD-STOP gates bind. Read `CLAUDE.md`
and `.claude/skills/reproduce-first/SKILL.md` first.

## What is actually missing, in the reviewer's words

| dim | now | gap the reviewer named |
|---|---|---|
| 1 | 13/20 | "It has never closed unattended." One candidate per turn; the holdout is read by no automated comparison. |
| 2 | 14/20 | One lesson, one corpus, one model. Nothing shows the layer helps twice. |
| 3 | 8/10 | The judge has only been scored where 15 of 18 cases pass; no self-preference control in the *choosing* path. |
| 6 | 8/10 | Five rejected candidates were built on; none produced a keeper. |
| 7 | 5/10 | Real signal, yes — from the owner's own repo. Never a third party. |

**Arithmetic, stated before starting.** 1 (+7) + 2 (+6) + 3 (+2) + 6 (+2) =
**+17 → 95 is reachable only with dimension 7's last five**, which need
someone else's repository. Without it the ceiling is **90**. No increment
manufactures a point; a dimension moves on an artifact a stranger could find.

## P1 — the unattended night (dim 1, +7 available)

The loop has never run a night on its own and produced a result a person
read the next morning. Everything else in this file is downstream of that.

- The nightly job runs against the **peptide pilot repo**, on a schedule,
  with a memory file something actually writes to, and a base branch that
  exists. Every prerequisite for this landed in the last two waves; nothing
  has ever been left alone to use them.
- **More than one candidate per turn.** The reviewer's second clause. Today
  a turn proposes once and stops; a night is worth having only if a turn can
  try several and keep the best that survives the gates.
- **The holdout is read by an automated comparison.** It exists, it is
  refused without an explicit flag, and no scheduled run has ever spent it.
  Decide in writing whether a nightly may, and if not, what does read it.
- Deliverable: a morning report from a run nobody watched, with the ledger,
  what it proposed, what the gates said, and what a person must decide.

## P2 — the second lesson (dim 2, +6 available)

One lesson, learned once, on one corpus, with one model, is an anecdote.

- Drive enough real work through the pilot repo that a **second distinct
  failure signature** recurs and consolidates. The first came from a word
  cap; the second must come from something else, or it is the same finding.
- Then the measurement that has never been possible: does the layer help
  when lessons **compete**? Every result so far is from a store holding
  exactly one entry, which is why the ranking knob is off on judgement
  rather than measurement.
- **Falsification:** if a second entry never forms, say so and say what the
  corpus would need. If it forms and the arms do not separate, dimension 2
  does not move and three measurements agree.

## P3 — a fair test for the judge (dim 3, +2 available)

The judge has only been graded where almost everything passes, so "answer
pass to everything" scores as well as thinking.

- Build the harder set: cases where a *correct-looking* answer is wrong —
  a right number with the wrong unit, a confident claim the source does not
  support, an answer to a neighbouring question. The pilot repo's own data
  supplies these.
- Re-run the judge comparison on it, including the control where one model
  grades its own writing against another's.
- **Falsification:** if the judge is no better than "pass everything" on
  hard cases, that is the finding and the point is not taken.

## P4 — a problem worth climbing (dim 6, +2 available)

Five rejected attempts were built on and none produced a winner, because the
proposer's next move is a fixed function of where it starts.

- Find or build a task where the *second* step is only reachable from the
  first — measured, not assumed, the way the staircase was measured before.
- Run both arms on it. **Falsification:** if no rejected attempt leads to a
  keeper again, that is three measurements, and the ADR says plainly whether
  the mechanism should be deleted.

## P5 — the third party (dim 7, +5 — OWNER ACTION)

Everything measured is one person's repositories, one writing style, one set
of habits. A convention all of them share is exactly what none of them can
detect.

**The ask is small:** one repository belonging to somebody else. A friend's
side project is enough. It must not be the owner's.

Until then, this loop states the ceiling as **90** and does not round up.

## Rules this loop adds

- **The nightly must be left alone.** A run watched and nudged is not the
  thing dimension 1 is asking for. Start it, walk away, read the morning.
- **A second lesson must come from a different failure**, not the same one
  seen twice.
- **Two measurement branches may not touch one corpus** — the merge-order
  lesson, learned the expensive way.
- Workers: own scratch directory; explicit exit-code checks before any push;
  byte-verified backups for every mutation.

## Report

Append to `docs/research/upgrade-2026-09-04.md` as a third wave, with the
final number beside 95 and the ceiling argument intact.
