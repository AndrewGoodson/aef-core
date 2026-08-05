# ADR 0083: An audit trail that outlives the process

## Status
Accepted. Phase 2 item 2b, plus the leftover from ADR 0079 F13.

## Context

`roadmap.md` listed `AuditLogWriter` under **Phase 1 — DONE**. The interface
was done. What shipped alongside it was `InMemoryAuditLogWriter`, the only
implementation, so **every audit entry died with the interpreter that wrote
it.** And a `PolicyEngine` constructed without an explicit writer stored the
default on `self._audit_log` with no accessor — the entries were written and
then unreachable.

An audit trail is consulted after an incident. That is the only time anybody
consults one. A trail that does not survive the process cannot be consulted
after anything.

The instruction was: make the roadmap true or make the roadmap honest. True
was cheap, so true.

## Decision

`FileAuditLogWriter` — append-only JSONL, alongside `FileMemoryStore`. Wired
by `aef run --audit-log <path>`. `PolicyEngine.audit_log` is now a property,
so the default writer is reachable.

**Argument values are redacted by default.** A tool call's `arguments` is
where an API key, a bearer token or a customer record lives. An audit log is
exactly the file that gets shipped to a log aggregator, attached to a ticket,
or read by whoever is debugging at 2am. The argument *names* are what make
the entry useful — which tool, which parameters, what the engine decided —
and the *values* are what make it dangerous. Verified: a call carrying
`api_key="sk-live-..."` produces a file containing `api_key` and not the key.

`redact_arguments=False` exists for the case where the destination is as
trusted as the arguments are sensitive. It is a decision, so it is a
parameter, not a default.

Two smaller properties, both matching `FileMemoryStore`'s stated reasoning:
an argument that will not serialise is stored as its `repr` rather than
losing the whole entry, and a malformed line **raises** rather than being
skipped — a log that silently drops records is worse than one that admits it
is damaged.

## Also here: the green bar's first command failed on day one

ADR 0079 found that the prescribed green bar failed 4/4 in a fresh adoptee.
The `mypy --strict aef` and `ruff format --check aef tests` halves were
fixed; bare `pytest -q` was not. A freshly adopted repo has no tests, so
`pytest -q` exits **5** — the first command of the bar, on the first day.

That is not a bug. It is the bar telling the truth. But it was prescribed
with no warning, so it reads as a broken repo, and it is the same exit code
that fails G1 if you pass `pytest -q` as `--build-command`. Both canonical
files now say so.

## Consequences
- Adopters get a durable audit trail by passing one flag, and get argument
  redaction whether or not they thought about it.
- `docs/roadmap.md`'s Phase 1 claim is now true as written, and a test
  asserts the roadmap names the durable writer so the claim cannot drift back
  to describing an interface alone.

## Confidence
High: redaction, durability across writers, the damaged-log path and the
unserialisable-argument path are each exercised. **Not claimed:** that the
audit log is complete as a security control. It records what `PolicyEngine`
evaluated. It does not record tool calls that never reached the engine,
which — since nothing forces a node to route its calls through one — is a gap
that configuration cannot close and only the node contract could.
