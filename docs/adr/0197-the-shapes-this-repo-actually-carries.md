# ADR 0197: The shapes this repo actually carries

## Status

Accepted. Worker **N5** of `ABOVE_95_LOOP.md` (increment N6, next-steps #10),
branch `upgrade/n5-measure-and-redaction`. Erratum appended to ADR 0163 §5.
Claims **no rubric point** on its own — dimension 4 is N3's row.

## Context

M6's pilot (ADR 0163) ran ADR 0119's redaction scan over five real recorded
runs of a real repo and reported 0 substitutions, 0 output-scan matches, and a
planted-fault control that caught 5 of 5 shapes. It then named its own
residual, which is the reason this increment exists:

> marlin's own subscription UUID: substitutions=0

Marlin's boundary rule is written around one identifier — a subscription UUID
quoted in its own `AGENTS.md` — and the shipped pattern list did not match it.
The reason was a correction, not an oversight: ADR 0126 removed `-` from
`opaque_secret`'s character class because
`migrate-the-customer-billing-pipeline-to-v2-with-zero-downtime` — a plain
English objective — was being redacted into a placeholder, and a scenario whose
objective is a placeholder no longer tests what the run did.

So the pilot scanned clean partly because the scanner could not see a
hyphenated identifier.

## Reproduced first

`python docs/research/pilot-marlin/scan_control.py --verify`, before any edit,
with the eleven shapes a real repo carries planted one at a time:

```
  uuid                substitutions=0  -> ...(contact 7e16b0bb-b75a-4a16-9765-839cf1b96755)
  slack_token         substitutions=0  -> ...789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx)
  jwt                 substitutions=2  -> ...ACTED:opaque_secret].[REDACTED:opaque_secret])
  github_token        substitutions=1  -> ...ion service (contact [REDACTED:opaque_secret])
  connection_string   substitutions=1  -> ...stgres://svcuser:[REDACTED:email]:5432/marlin)
```

Five findings in one command, and only the first was known:

1. **A UUID passes** — ADR 0163's residual, confirmed.
2. **A Slack token passes.** `xoxb-…` is hyphenated, and nothing was
   prefix-anchored on `xox`.
3. **A JWT is torn in half.** `opaque_secret` excludes `.`, so a JWT matched as
   *two* opaque secrets — the report says a thing leaked twice and names
   neither of them a token.
4. **A GitHub token is reported as `opaque_secret`.** Caught, mislabelled. An
   operator reading "opaque_secret" does not know to go and revoke a PAT.
5. **A connection string is reported as `email`**, and `svcuser:` survives in
   the clear: the `user:password@host` tail is email-shaped, so the *email*
   pattern won the race and the operator is sent to rotate a mailbox.

The point 3–5 make together is that a label is not cosmetic. "Something opaque
leaked" and "your production database URL leaked" are different incidents.

## Decision

Six shapes added to `DEFAULT_PATTERNS`, each with its own name, and one
existing pattern widened. Order is load-bearing and stated in the source.

| label | shape | why it is not a shape-guess |
|---|---|---|
| `connection_string` | `scheme://user:pass@host` | placed **first**, ahead of `email`, so the credential is named for what it is |
| `jwt` | three dot-separated base64url segments with a JOSE header | placed **after** `bearer`, so `Bearer <jwt>` stays a bearer header |
| `uuid` | 8-4-4-4-12, hex-only, length-exact | this is ADR 0163's residual |
| `github_token` | `gh[pousr]_` + 30+ | prefix-anchored |
| `slack_token` | `xox[baprse]-` + 10+ | prefix-anchored |
| `aws_key` (widened) | `AKIA` plus `ASIA`/`ABIA`/`ACCA`/`AIDA`/`AROA` | AKIA-only missed every temporary and role id |
| `api_key` (widened) | up to three short segments between prefix and body | see below |

**`sk-` was already covered and `sk-ant-` was not.** The old `api_key` pattern
was `\b(?:sk|pk|rk|ak)[-_](?:live|test|ant|proj)?[-_]?[A-Za-z0-9]{16,}\b` — a
fixed vocabulary of exactly one optional middle segment. On
`sk-ant-api03-<36 chars>`, the shape of a **real Anthropic API key**, `ant`
consumes the vocabulary slot and `api03` is then left in front of a character
class with no hyphen: it matched **nothing at all**. This is the credential an
adopter of *this* repo is most likely to be holding. The middle is now
`(?:[-_][A-Za-z0-9]{2,10}){0,3}`, which follows the vendor convention instead
of a list of four words somebody happened to think of.

**Ordering, not weakening, is how the UUID gets in.** `-` is still absent from
`opaque_secret`. The `uuid` pattern cannot revive ADR 0126's false positive
because every one of its five groups is hex-only and length-exact, so a
hyphenated English slug has no substring that fits.

### `find()` now reports what a redaction would actually stamp

`RedactionPolicy.find` searched the raw text with every pattern independently.
One leaked database URL came back as `("connection_string", "email")`: two
findings for one credential, the second naming a thing nobody has to rotate.
`find` now applies the patterns in order, each to the text the previous ones
substituted — the same way `redact_text` works.

This does not weaken the detector, and the argument is short enough to check:
if any pattern matches the raw text, let P be the first such in list order; no
pattern before P matched, so nothing before P changed the text, so P still
matches. Non-empty before ⟺ non-empty after.

### The seam it opened, found by the full suite

A run id is a `uuid4` **the harness assigns**. Once `uuid` was a pattern, the
output scan matched the scenario's own `id` and its `initial_state.run_id`, and
`tests/cli/test_run.py::test_a_recorded_run_re_executes_identically_and_is_
harvested` went red: **every harvest of a recorded run was rejected "a secret
survived redaction"**. That is ADR 0126's F12 exactly, one field over — the
cassette digest, then the run id.

The fix is the same one, and deliberately so: `harvest._scannable` drops the
harness's own identifiers **by exact field path**, never by teaching a pattern
to ignore a shape. `_HARNESS_IDENTIFIERS = (("id",), ("initial_state",
"run_id"))`. A UUID a tenant typed into an objective, or one a tool returned,
is still scanned and still rejects the run — which is the entire point of the
`uuid` pattern, and is what
`test_the_harness_own_run_id_is_dropped_from_the_scan_but_a_typed_one_is_not`
pins from both sides.

## The controls, which are half the test file

`tests/harness/test_redaction_shapes.py` runs 15 planted positives (each
asserted to be reported **under its own label**, with `count == 1`) against 9
negatives that must still not match: ADR 0126's hyphenated English objective,
its versioned variant, its long snake_case identifier, an ordinary objective, a
plain https URL, a host and port with no credentials, a date range, a semver
with build metadata, and a short hex id.

**One honest caveat, stated rather than smoothed over.** A 64-character SHA-256
request digest still matches `opaque_secret`, and always has since ADR 0126 —
that false positive is contained by `_scannable` dropping `RecordedCall.key`,
not by the pattern. What this ADR had to avoid was adding a *second* label to
it, which would make the digest match a shape `_scannable` has no reason to
know about. `test_the_cassette_digest_matches_no_new_shape` asserts exactly
that, and then demonstrates the containment on a payload.

## What the scanner now finds in artefacts already committed

The whole of `docs/research/` and the whole of `corpus/`, line by line, with
the new list. **No credential was found.** Every match falls into one of three
classes, and each is a harness-generated identifier rather than tenant text:

| what | where | count |
|---|---|---|
| `uuid` — run ids, session ids, and the scratch-session path segment | `pilot-marlin/*.txt`, `00-preflight.json` | 58 |
| `opaque_secret` — `RecordedCall.key` digests, `prompt_sha256`, the audit ledger's `entry_hash`/`previous_hash` chain | `corpus/**` (39), `i12/`, `pilot-marlin/13-ledger.json` | 66 |
| the planted controls themselves | `06-redaction-control.txt`, `scan_control.py` | 7 |

Two of those are worth writing down. The **audit ledger's hash chain** matches
`opaque_secret`, so a harvest that ever scanned a ledger would reject it — the
same class of false positive as the cassette digest, in a file `_scannable`
does not cover. And the **scratch session directory** in this repo's own
tooling paths is UUID-shaped, so any transcript quoting a path matches `uuid`.
Neither is a leak; both are reported here because a scan whose output is
un-triaged is a scan nobody read.

**The one real identifier, and the judgement made about it.** ADR 0163 §5,
`06-redaction-control.txt`, and the control script all quote marlin's
subscription UUID verbatim — deliberately, as the evidence for the residual.
It is an Azure subscription id, not a credential: it authorises nothing without
a login, and it is published by its owner in marlin's own committed
`AGENTS.md`, which is where ADR 0163 read it. It was **not** retro-redacted
here, and the reason is the same one ADR 0110 gives for keeping verbatim
feedback beside a summary: redacting the four places it stands would make ADR
0163's finding untraceable to what was observed, and would leave the value in
marlin's repo regardless. **This is a judgement, it is the owner's to overturn,
and the scanner now catches the shape**, so nothing harvested from here on
carries one out.

## Mutation results

Each of the five new patterns deleted in turn, suite re-run, file restored and
`shasum -a 256` verified against the backup each time:

| dropped | tests that failed |
|---|---|
| `uuid` | 4 — both planted positives, `..._travel_through_redact_state`, the sampleless-pattern guard |
| `jwt` | 2 |
| `github_token` | 3 — both positives + the guard |
| `slack_token` | 3 |
| `connection_string` | 5 — three positives, `..._not_reported_as_an_email`, the guard |
| `api_key` reverted to its pre-0197 pattern | 1 — `sk-ant-api03-…` |

## Consequences

- ADR 0163's residual is closed in the code. Its committed `.txt` is not
  rewritten; an erratum in that ADR carries the new number and `make measure`
  pins the line against the erratum (ADR 0196).
- Adopters get eleven named shapes instead of five, and a report that says
  which one matched.
- The false positive ADR 0126 removed stays removed, under test, nine ways.
- `_scannable` now has two entries in its drop list rather than one, and the
  rule for adding a third is written down: harness-generated, exact path, never
  a pattern exemption.

## Confidence

High. Every finding here was produced by running the scanner, not by reading
it; the seam was found by the full test suite going red rather than by
inspection; and every pattern is mutation-checked against a planted positive
and a named false positive. The one soft spot is the negative list: nine
controls is what ADR 0126 named plus six more, and a false positive nobody has
thought of is by construction not on it.
