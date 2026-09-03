---
name: reproduce-first
description: Use when verifying, auditing, or fixing anything in this repo - the method that found ten defects, extracted so it is enforced rather than remembered
---

# Reproduce first

Ten defects were found in this repo. Every one came from **running something**,
not from reading it. Several had passing tests and had survived review. This
file is that method, extracted from seven loop prompts so it stops depending
on anyone remembering it.

## The rules

**Construct the failing case and RUN it.** A defect you have not reproduced
is a hypothesis. Build the malformed input, the hostile git repo, the
candidate that should pass — and execute it against real objects. Never
against a mock of the thing under test.

**Report reproduced and suspected separately.** Never blur them. "I think X
might be wrong" and "here is the command that proves X is wrong" are
different claims, and mixing them makes the whole report untrustworthy.

**Assert every patch applied — before and after.** Three times in this
program a patch silently no-opped (an indentation mismatch, a wrong anchor)
while the script printed "fixed". Tests caught them; nothing else would have.

```python
assert old in text, "anchor not found — this patch would silently no-op"
text = text.replace(old, new)
assert new_marker in text, "patch did not take"
```

**Verify a detector against a planted fault before trusting "nothing
found".** A scanner that cannot detect is not a scanner. One audit script in
this program returned a false negative on the very claim it was checking, and
was only caught by reading the source afterwards.

**Green bar before every commit**, all four:

```
pytest -q ; mypy --strict aef ; ruff check . ; ruff format --check aef tests examples
```

Test count grows or holds. It never silently shrinks.

**Never weaken a control to make something pass.** If a control is wrong,
propose replacing it and say why. Loosening a threshold to get green is how a
gate becomes decoration.

**A test that pins wrong behaviour is worse than no test**, because it
defends the defect through every refactor. When a fix changes behaviour, look
for the test asserting the old behaviour and update it deliberately — one was
pinning an anti-correlated detector in this repo.

## Where defects actually lived

Three of ten were in **seams** — joins between components that were each
correct and each tested: a floor passed as its own minimum, a store
constructed empty, a default assuming another repo's layout. Component tests
cannot see wiring. When something is green but does not work, look at the
join before the parts.
