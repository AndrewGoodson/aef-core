# ADR 0120: The prompt surface is under test

## Status
Accepted. Increment I8 of `IMPROVE_LOOP.md`; record in `IMPROVE_LOG.md`.

## Context

`/new-model-check` (ADR 0111) audits every prompt surface against the
current model guide and applies its edits: remove text the model
over-obeys, add the blocks it needs for unattended runs, keep the
verification instructions. Nothing then stopped the next commit from
putting back what was removed or trimming what was added. The rubric's
dimension 5 lost a point for exactly this: prompt changes were unmeasured.

A prompt eval — running the model against the prompt and scoring the
output — does not exist here and would cost a model call per assertion.
What can be pinned without one is the *state the last check left*, the
way `tests/test_model_ids.py` pins the shape of a model ID without a table
of models.

## Decision

`tests/test_prompt_surface.py` asserts, over this repo's instruction files
and the renderers that ship instructions into adopted repos:

1. the unattended-run surfaces carry the guide's blocks (autonomy, scope,
   targeted edit), compared on the joined blockquote so wrapping is not a
   failure;
2. no surface carries text the guide removed — anti-narration,
   anti-formatting, `CRITICAL: YOU MUST` escalation — outside code spans
   and outside lines that name the pattern as a thing to avoid;
3. the verification instructions the guide says to keep — reproduce first,
   the green bar — are present in every contract a session reads first;
4. **every detector is proved against a planted fault** before the other
   tests are believed.

## Evidence

The planted-fault test found a defect in its own detector on the first
run: the anti-formatting pattern was case-sensitive and "Never use bullets"
sailed past it. The verification check found a real gap: the `CLAUDE.md`
that `aef adopt` ships carried no reproduce-first instruction — it pointed
at `AUTONOMY.md` and said nothing itself, so a session reading only the
first file a harness loads had no verification rule. Both fixed. Two
mutations — trimming the autonomy block's load-bearing first sentence;
appending "Do not narrate your steps." to `CLAUDE.md` — each failed tests.

## Consequences

- Rubric dimension 5: 9 → 10. Prompt-surface edits now have a check that
  fails when they regress. It is a lint, not an eval; the ADR says so.
- `/new-model-check` should update this file's `REQUIRED_BLOCKS` and
  `FORBIDDEN` when a guide changes them, and the skill's Step 6 now names
  it as a file the run edits.

## Confidence

High on what it pins; it measures presence of text, not effect on a model.
