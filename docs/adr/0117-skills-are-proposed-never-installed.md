# ADR 0117: Skills are proposed, never installed

## Status
Accepted. Increment I7 of `IMPROVE_LOOP.md`; record in `IMPROVE_LOG.md`.

## Context

WikiSkill's loop has three layers: raw experience, a persistent wiki, and
executable skills that a skill updater rewrites at runtime. ADR 0110 built
the middle layer and said the third is `aef/evolution/`, hard-disabled by
constraint #7, and out of scope. That was correct about runtime
self-modification and too broad about the layer: the *content* of a skill
— what an agent should do differently next time — is exactly what a
well-evidenced `KnowledgeEntry` already holds. What was missing was the
step from entry to a file a person can review, and every honest version of
that step ends at a person.

## Decision

1. **`aef loop skills` renders drafts, under a proposals directory the
   caller names.** One `SKILL.md` per entry at or above `min_occurrences`
   (default 3, one more than the consolidator's own threshold — a skill is
   a stronger claim than a lesson).
2. **Never under a harness directory.** `.claude/`, `.cursor/`, `.github/`,
   `agents/` are refused by name, before anything is written. A draft that
   landed where a coding agent loads skills would be a runtime
   self-modification with extra steps — the thing `aef/evolution/` is
   disabled to prevent.
3. **Never overwrites.** A draft a person has edited is theirs.
4. **Every claim in the draft is computed from the entry.** Occurrence
   count, confidence, `runs_since_last_seen`, run ids, first/last seen and
   provenance ids come from the store; the lesson text is the entry's own.
   The module imports nothing from `aef.evolution`, `aef.providers` or
   `aef.reasoning`, asserted by an AST test.
5. **The knowledge store is rebuilt from the durable memory file** at
   command time, because the consolidator is a stateless recompute (ADR
   0110) and no file-backed knowledge store exists. The memory file is the
   evidence; the drafts are derived from it every time.

## Evidence

Eleven tests: provenance fields present, slug stable and filesystem-safe,
one draft per qualifying entry, existing drafts untouched, each of the four
harness directories refused with nothing created, agent scoping, the AST
import check, and the CLI end to end including its refusal as a non-zero
exit rather than a traceback. Three mutations (write under harness dirs,
overwrite drafts, ignore agent scope) each failed tests.

## Consequences

- Rubric dimension 2: 12 → 15. The skill layer now has a governed output.
  What it lacks is any measurement of whether an adopted skill helps — that
  needs a person to adopt one and the task metric to move, and neither has
  happened.
- `aef/evolution/` is untouched. The trust case's three findings are
  untouched. A skill proposal changes what an agent is *told*, by a person,
  not what a graph *can do*.

## Confidence

High on the refusals; the value of the drafts is unmeasured until one is
adopted.
