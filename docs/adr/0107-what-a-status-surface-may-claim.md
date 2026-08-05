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

## The second adversarial round

Round 1 found three, so a fresh round was owed before the milestone could
close. It found three more, on angles round 1 did not touch.

**B1 — `unknown_when` was documentation.** Every panel listed the reasons it
could be unknown for, and nothing checked. The halt panel cheerfully reported
`corpus_empty`, which sends the operator to fix the corpus while the loop is
halted. This is ADR 0092's defect class ("a declared thing with no enforcement
reads as an enforced thing") and ADR 0074's ("a refusal that misnames its own
cause sends the operator to fix the wrong thing") in the same line of code —
and the milestone's own instruction 1a was to specify exactly this per panel.
`Panel.__post_init__` now refuses an undeclared reason.

**B4 — four `UnknownReason` members no panel could display**, including the
most security-relevant one. `LEDGER_UNVERIFIED` had no home: the ledger panel
could not say "nobody checked this chain." It is now declared there, and
renamed `LEDGER_NOT_VERIFIED` because the old name blurred two different
claims — a chain that was **not checked** is UNKNOWN; a chain that **failed**
verification is `Known(..., DEGRADED)` and loud. Collapsing them would let a
detected forgery render as an absence, which is the quieter and worse of the
two.

The other three (`EXPORT_MISSING`/`STALE`/`UNREADABLE`) belonged to the fleet
page, which does not exist until Milestone 4. They were **deleted**, not
deferred — ADR 0101's rule turned on this module's own code. They return with
the panels that consume them, and `test_every_unknown_reason_has_a_home` makes
adding one without a panel fail.

**B3 — a `Known` subclass overriding `__post_init__`** renders green over
`None`. A malicious subclass is not the threat model, so this is low severity;
the fix is a re-check at `Panel`, on the same reasoning that kept the zone rule
alive through three defeats of the allowlist (ADR 0093) — being the only check
is the problem.

### What round 2 left open, deliberately

**The disclosure registry has no production caller.** `disclosure_of` is called
by nothing outside `contract.py` — which is ADR 0092's defect class pointed
straight at rule 3 above. It is *expected* at Milestone 1, which is
contract-only by construction, but "expected" is how an unkept promise starts.
It is therefore **Milestone 2's acceptance criterion**: the export must route
every field through `disclosure_of`, and a test must fail if it does not.

Worth recording that the AST check which found this initially reported a
caller — it had matched `emittable`'s own internal call inside `contract.py`.
A detector that counts the definition site as a caller would report "wired" for
every dead registry in any codebase.

## The third adversarial round

Four more, all reproduced. Round 3 aimed at the registries and at whether the
API's own names would mislead the caller Milestone 2 was about to be.

**C4 — `emittable()` was a trap, and the trap was aimed at the next
milestone.** It returned `True` for `REDACTED`, so the obvious caller —

```python
if emittable(field):
    payload[field] = value
```

— emitted the raw `error_message` and the raw `tenant_tag`, which are exactly
the two fields the registry marks as needing redaction. The function was
correct against its own docstring ("may appear in the export at all, in any
form") and wrong against every way anyone would use it. That is the more
dangerous kind of correct, and rule 3 above would have been decoration the
first time the export was written.

`emittable` is **removed**, not deprecated: leaving it importable keeps the
"safe to emit" reading available at every call site. A three-valued policy now
gets a three-way function that applies the policy itself:

```python
prepare("signing_key", ...)      -> DisclosureError
prepare("error_message", conn)   -> 'sha256:572c286c4416fdf6'
prepare("merged", 7)             -> 7
```

The safe path is the only path. `redacted_form` is a stable truncated digest so
the fleet page can still count distinct tenants and group identical errors —
and its limit is stated rather than implied: it stops the value being *read*,
it does not make it unguessable. A digest over a low-entropy domain is
confirmable by anyone holding a candidate list. Fixing that needs a key, and a
key in the export is the ADR 0106 mistake with the serial numbers filed off.

**C1 and C3 — both registries were plain dicts.** One assignment
(`PANELS_BY_KEY["halt"] = PanelSpec(..., unknown_when=tuple(UnknownReason))`)
switched off the enforcement round 2 had just installed, and
`FIELD_DISCLOSURE["signing_key"] = Disclosure.PUBLIC` flipped an EXCLUDED field
to PUBLIC at runtime. Deciding a disclosure and then leaving the decision
writable is most of the way back to not having decided. Both are
`MappingProxyType` now.

**Not a defect: `Panel` accepts a `PanelSpec` outside the catalogue.** Checked
and deliberately left. `PANELS` is a default, not a whitelist — an adopting
repo will want panels this repo has never heard of — and the `unknown_when`
enforcement is per-spec, so it still holds for any spec anyone brings.

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
