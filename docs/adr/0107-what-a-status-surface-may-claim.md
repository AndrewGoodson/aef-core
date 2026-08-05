# ADR 0107: What a status surface may claim

## Status
Accepted. Milestone 1 of the "make the loop legible" program. Contract only —
no rendering code exists yet, deliberately.

## Context

The loop already records what an owner needs: `ledger.jsonl` is a hash-chained
event log, `Digest` carries twelve counters, `Graph.visualize()` emits Mermaid,
every node execution emits an OTel span, and `aef loop status|digest|doctor`
print the state as text. None of it is lookable-at. The oversight surface is a
CLI invocation somebody must remember to run, per repo, one repo at a time.

Building the page is easy. The hard part is that **a dashboard is a trust
surface**: a wrong number on it is believed by someone who has stopped reading
the underlying data — which is precisely why they wanted a dashboard. So the
constraints go into a type before they go into a template.

## Decision

Three rules, each enforced structurally rather than by convention.

### 1. A panel with no data cannot render green

`Reading[T]` is a closed union of `Unknown` and `Known[T]`. `Unknown` has **no
`state` field at all**, so there is no branch in which an empty panel produces
`HEALTHY`, and `mypy --strict` rejects any unnarrowed access:

```
build/dash_narrowing_check.py:5: error: Item "Unknown" of "Unknown | Known[int]"
has no attribute "state"  [union-attr]
```

That error is asserted by a test that shells out to `mypy` — the claim is that
the type checker stops you, so the test runs the type checker. A runtime-only
test would prove today's code happens not to do it, not that the next person
cannot.

`Unknown` carries an `UnknownReason` enum rather than free text, because the
operator's next action differs per cause and "unknown" with no cause sends
them to the wrong place — the defect class ADR 0074 named.

This rule is not new here. `Digest` already carries `halt_channel_configured`
and `runs_recorded` for one reason stated in its own source: *"a system that
reports nothing looks identical to one with nothing to report."* A dashboard is
where that stops being a nuisance and becomes authoritative.

### 2. The page is read-only

`FORBIDDEN_HTML_CONSTRUCTS` is declared in the contract and imported by the
renderer's tests rather than re-listed there — the derived-not-duplicated rule
the gate catalogue follows, because two lists nobody compares drift (ADR 0091).

A dashboard with controls is an unaudited control plane reachable by anyone who
can open a file: no authentication, no audit-log entry, no HITL gate. The loop's
approval story routes through a signed manifest held by a person (ADR 0103); a
button on a web page is a second door into it that nothing in this repo records.
The list covers four distinct mechanisms, not four spellings of one — `<form>`,
scripted handlers, `fetch`/`XMLHttpRequest`, and the ones people forget
(`sendBeacon`, `WebSocket`).

### 3. No field is emitted whose disclosure nobody decided

`disclosure_of()` **raises** on an unregistered field. A default would apply
somebody's guess to every field added later, which is how a decision becomes an
accident. Each entry in `FIELD_DISCLOSURE` is `PUBLIC`, `REDACTED` or
`EXCLUDED` with a reason.

Two of those decisions are load-bearing and neither was obvious:

- **`error_message` is REDACTED, `error_type` and `error_count` are PUBLIC.**
  Error text is the field most likely to carry a secret by accident — a
  traceback that stringifies a connection URL, a client that echoes an
  `Authorization` header. Type and count answer the operator's actual question
  ("is it failing, and how"); the message does not, and cannot be scanned safely.
- **`canary_salt_fingerprint` is EXCLUDED.** ADR 0106 made it a
  200k-iteration PBKDF2 precisely because it is an offline oracle against the
  salt. An export is a file that gets committed and pasted around; publishing
  the fingerprint hands an attacker the oracle *and* the leisure to grind it.
  Restarts prove same-population against a fingerprint in the loop state, not
  one in the export. `canary_keyed` stays PUBLIC — whether keying is on is
  exactly what an operator must be able to see.

`tenant_tag` is REDACTED for a duller reason that is just as real: a tenant tag
list in a shared file is a customer list.

## The adversarial round, and what it cost

Three attacks, all **reproduced**, all against code written minutes earlier and
believed correct.

**A1 — the module's central claim, defeated in four lines by a shipped API.**

```
Digest(...).acceptance_rate  ->  None       # when proposed == 0
Known(value=None, state=HEALTHY)            # accepted
panel.state=healthy is_green=True
```

`Digest.acceptance_rate`, `Digest.beating_manual_editing` and
`MonitorResult.observed_pass_rate` all return `X | None`, where `None` means
"nothing to compare". That is UNKNOWN wearing an `Optional`, and the first
adapter anyone wrote would have produced a green dashboard for a loop that had
never run. `Known` now refuses `value=None` — the None branch of an optional
**is** the Unknown branch — and `Known.optional()` provides the correct
spelling, because refusing None without offering it just relocates the mistake
to `Known(value=x or 0, ...)`.

**A2 — `PanelState` is a `StrEnum`, so its members are strings.**
`Known(value=1, state="unknown")` compared unequal to every member under `is`
and slipped past the contradiction guard. `isinstance(state, PanelState)` is
now required.

**A3 — duck typing at a trust boundary.** Any object carrying
`.state = HEALTHY` rendered green, because `isinstance(reading, Unknown)` was
`False` and the else-branch trusted whatever it was handed. `Reading` is a
closed union of two cases and is now closed at runtime as well as in the type.

Each regression test is built from the **real** API — the actual `Digest`, the
actual `evaluate_window` — never a literal `None` standing in for one. Twice in
the predecessor program a detector passed its own planted fault and was still
wrong, both times because the fault was a paraphrase.

### A fourth, from the tooling rather than the code

`ruff check --fix` rewrote `("unknown" is PanelState.UNKNOWN) is False` into
`==` (rule F632, autofixed), which inverts the exact gap that assertion
documents — the test then failed, loudly, which is the only reason it was
noticed. The literal is now bound to a name so the autofix does not apply. A
linter silently changing what an assertion proves is the "test that pins wrong
behaviour" hazard from `reproduce-first`, arriving from a direction that skill
does not mention.

### The boundary case, decided rather than omitted

`Known(value=[], state=HEALTHY)` is **allowed**. Empty is not absent: zero
recorded errors is a real, healthy answer, and refusing `[]` the way `None` is
refused would force UNKNOWN for a question the source can actually answer.

## Consequences

Milestone 2's export must map every optional source through `Known.optional`
and name an `UnknownReason` for each — which is the work, and is the point.
Ten panels are specified with their UNKNOWN conditions; a `PanelSpec` declaring
none is refused at construction, because "it shows unknown when there's no
data" is a sentence that sounds complete and specifies nothing.

## Alternatives rejected

**A boolean `healthy` plus a `has_data` flag.** Two fields nobody compares, and
the failure mode is a caller who sets the first and forgets the second — which
is exactly A1, in a form no type checker could catch.

**Defaulting unregistered fields to `REDACTED`.** Safe-looking and wrong: it
makes the disclosure decision silently, for fields nobody looked at, and the
first person to notice would be whoever wondered why their counter rendered as
`***`.
