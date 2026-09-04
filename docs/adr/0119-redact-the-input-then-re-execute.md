# ADR 0119: Redact the input, then re-execute

## Status
Accepted. Increment I5 of `IMPROVE_LOOP.md`; record in `IMPROVE_LOG.md`.
Redaction is **on by default** in `harvest`; `redaction=None` turns it off.

## Context

The machinery to learn from real runs already existed: `aef run
--record-runs` captures them, `harvest` promotes failures into the corpus
with a determinism re-check and a daily rate limit, `cycle` proposes from
what reflection wrote about them. The trust case says criteria 1 and 6 have
never run against live traffic or real tenants, and the rubric scored
dimension 7 at 2/10 for it.

One reason no owner would turn that on is not in the trust case: the
corpus lives in git, and a harvested run carries whatever the tenant
typed. "Learn from live runs" meant "commit tenant data".

## Decision

1. **Redact the input, then re-execute; never patch the recorded trace.**
   A trace with secrets replaced in place is a run that never happened — the
   agent saw the real values and acted on them. Harvest already refuses a
   run that does not re-execute identically; redaction reuses that: the
   redacted initial state is re-run under the recorded clock, and the run
   is admitted only if the *behaviour* is the same — node path, failing
   nodes, plan status. Text may differ; that is what redaction changes. A
   graph whose behaviour depended on the secret changes behaviour under
   redaction and is rejected, not recorded.
2. **Scan the output before writing.** The scenario that would be saved is
   scanned with the same patterns. A match means the graph reintroduced a
   secret from somewhere the input redaction could not reach — a tool, an
   environment — and the run is rejected. This is the planted-fault check
   on the redactor, run every harvest rather than once at authoring.
3. **Patterns are data, conservative, and only ever extended.** Emails,
   API-key shapes, bearer tokens, AWS keys, long opaque strings; secret-
   shaped `working_memory` keys are dropped outright. A false positive
   costs one scenario; a false negative costs a tenant.
4. **On by default.** A harvest that writes tenant text unless told not to
   is the wrong default for a corpus in git.

## Evidence

Planted through `harvest`: an email in the objective and a token in
working memory — promoted, both absent from every file on disk, the stored
trace is the re-executed one on redacted input, the notes say two
redactions were applied. A graph that fails only when the token is present
— rejected as behaviour changed, nothing written. A graph that emits the
token from its own code — rejected by the output scan. Redaction off —
the email reaches disk, which is the control proving the scan scans. Every
default pattern has a sample it matches. Four mutations (no output scan;
behaviour change not checked; secret keys not dropped; keep the unredacted
trace) each failed tests.

## Consequences

- Rubric dimension 7: 2 → 5. The ingestion path is now safe to point at a
  real tenant; it has still not been pointed at one, and that is the owner
  decision the trust case names. The remaining five points are that
  decision, not code.
- A redacted scenario re-executes on the redacted input by construction,
  so every downstream gate is comparing against a run that actually
  happened under exactly those inputs.
- Behaviour comparison is structural (path, failing nodes, status). Two
  runs that differ only in error text are the same failure here; two that
  differ in which node failed are not.

## Confidence

High on the mechanism. The pattern list is a floor: an owner with a
different secret shape extends it, and the output scan catches what the
input pass misses only when the secret has a recognisable shape.
