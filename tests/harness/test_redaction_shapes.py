"""The identifier shapes a real repo carries (ADR 0197).

M6's pilot (ADR 0163) scanned marlin clean and then named its own residual:
marlin's boundary rule is written around a subscription UUID, and the default
pattern list did not match it — because ADR 0126 had removed `-` from
`opaque_secret`'s character class to stop a hyphenated plain-English objective
being redacted into a placeholder.

So the fix has two halves and this file tests both, because half of it is a
regression waiting to happen:

* **(a) a planted positive per shape** — each new pattern matches the thing it
  is named for, and is REPORTED UNDER ITS OWN NAME. A scan that says
  "opaque_secret" when the leak was a database URL sends whoever reads it to
  rotate the wrong credential.
* **(b) the false positives ADR 0126 named must still not match** — the
  hyphenated English objective, the long snake_case identifier, and the
  cassette's own SHA-256 request digest. Half of this file is the control.

The mutation this file must survive: delete any one pattern from
`DEFAULT_PATTERNS` and exactly one `test_*_is_caught_under_its_own_name`
parametrisation fails.
"""

from __future__ import annotations

import pytest

from aef.harness.redaction import DEFAULT_PATTERNS, RedactionPolicy
from aef.state import AEFState

# ---------------------------------------------------------------------------
# (a) One planted positive per shape, with the label it must be reported under.
# ---------------------------------------------------------------------------
PLANTED: tuple[tuple[str, str], ...] = (
    # The residual ADR 0163 named, verbatim from marlin's own AGENTS.md.
    ("uuid", "7e16b0bb-b75a-4a16-9765-839cf1b96755"),
    ("uuid", "3F2504E0-4F89-41D3-9A0C-0305E82C3301"),
    (
        "jwt",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
    ),
    ("aws_key", "AKIAIOSFODNN7EXAMPLE"),
    ("aws_key", "ASIAY34FZKBOKMUTVV7A"),  # a temporary key id; AKIA-only missed it
    ("aws_key", "AROAJQABLZS4A3QDU576"),
    ("github_token", "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB"),
    ("github_token", "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab"),
    ("slack_token", "xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"),
    ("slack_token", "xoxp-2345678901-2345678901-2345678901-abcdef0123456789"),
    ("api_key", "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEf"),
    ("api_key", "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"),
    ("connection_string", "postgres://svcuser:hunter2correct@db.internal.example:5432/marlin"),
    ("connection_string", "mongodb+srv://admin:s3cr3t@cluster0.example.net"),
    ("connection_string", "amqp://rabbit:letmein@queue.internal:5672"),
)


@pytest.mark.parametrize(
    ("label", "planted"), PLANTED, ids=[f"{lbl}-{i}" for i, (lbl, _) in enumerate(PLANTED)]
)
def test_a_planted_secret_is_caught_under_its_own_name(label: str, planted: str) -> None:
    policy = RedactionPolicy()
    text = f"the run said: {planted} — retry"
    assert policy.find({"note": text}) == (label,), (label, policy.find({"note": text}))
    redacted, count = policy.redact_text(text)
    assert count == 1, redacted
    assert planted not in redacted
    assert f"[REDACTED:{label}]" in redacted


def test_the_shapes_travel_through_redact_state() -> None:
    """The policy is only useful where harvest calls it: on a whole state."""
    policy = RedactionPolicy()
    state = AEFState(
        run_id="r",
        agent_id="a",
        objective="reconcile subscription 7e16b0bb-b75a-4a16-9765-839cf1b96755",
        working_memory={
            "dsn": "postgres://svcuser:hunter2correct@db.internal.example:5432/marlin",
            "note": {"upstream": ["ghp_1234567890abcdefghijklmnopqrstuvwxyzAB"]},
        },
    )
    redacted, count = policy.redact_state(state)
    assert count == 3, count
    assert "[REDACTED:uuid]" in redacted.objective
    assert "hunter2correct" not in str(redacted.working_memory)
    assert "ghp_" not in str(redacted.working_memory)
    assert policy.find(redacted.model_dump(mode="json")) == ()


def test_a_bearer_header_carrying_a_jwt_is_still_reported_as_a_bearer_header() -> None:
    """Order is a claim: `Bearer <jwt>` is a bearer header, and splitting it
    into a `jwt` match would lose the fact that it was on the wire."""
    policy = RedactionPolicy()
    header = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpM"
    assert policy.find({"h": header}) == ("bearer",)
    redacted, count = policy.redact_text(header)
    assert count == 1 and redacted == "[REDACTED:bearer]"


def test_a_connection_string_is_not_reported_as_an_email() -> None:
    """Before ADR 0197 the `user:password@host` tail matched `email`, so a
    leaked database URL was reported as an email address — the operator is
    then told to rotate the wrong thing, and `svcuser:` was left in the clear."""
    policy = RedactionPolicy()
    dsn = "postgres://svcuser:hunter2correct@db.internal.example:5432/marlin"
    assert policy.find({"dsn": dsn}) == ("connection_string",)
    redacted, _ = policy.redact_text(dsn)
    assert "svcuser" not in redacted and "hunter2correct" not in redacted


# ---------------------------------------------------------------------------
# (b) The control. ADR 0126 removed `-` from `opaque_secret` for these. None of
#     ADR 0197's patterns may bring any of them back.
# ---------------------------------------------------------------------------
DIGEST = "a3f5" * 16  # 64 hex chars, the shape of a RecordedCall.key
NEGATIVES: tuple[tuple[str, str], ...] = (
    (
        "hyphenated English objective",
        "migrate-the-customer-billing-pipeline-to-v2-with-zero-downtime",
    ),
    ("leading versioned segment", "v2-migrate-the-customer-billing-pipeline-with-zero-downtime"),
    (
        "long snake_case identifier",
        "test_a_downstream_node_counts_as_a_recurrence_of_its_own_lesson",
    ),
    ("an ordinary objective", "settle the invoice for order 12345 by Friday"),
    ("a plain https URL", "https://docs.example.com/guide/quick-start?tab=python"),
    ("a host and port, no credentials", "postgres://db.internal.example:5432/marlin"),
    ("a date range", "2026-09-01/2026-09-05"),
    ("a semver with build metadata", "1.24.0-rc.3+build.4a5f"),
    ("a short hex id", "deadbeef-cafe"),
)


@pytest.mark.parametrize(("name", "text"), NEGATIVES, ids=[n for n, _ in NEGATIVES])
def test_a_known_false_positive_still_does_not_match(name: str, text: str) -> None:
    policy = RedactionPolicy()
    assert policy.find({"objective": text}) == (), (name, policy.find({"objective": text}))
    state = AEFState(run_id="r", agent_id="a", objective=text)
    assert policy.redact_state(state)[0].objective == text


def test_the_cassette_digest_matches_no_new_shape() -> None:
    """The one honest caveat, stated rather than smoothed over.

    A 64-character SHA-256 request digest DOES match `opaque_secret`, and has
    since ADR 0126 — that false positive is contained by `harvest._scannable`
    dropping `RecordedCall.key` before the output scan, not by the pattern.
    What ADR 0197 must not do is add a SECOND label to it, which would make the
    digest match a shape `_scannable` has no reason to know about.
    """
    policy = RedactionPolicy()
    assert policy.find({"key": DIGEST}) == ("opaque_secret",)
    assert policy.find({"key": f"sha256:{DIGEST}"}) == ("opaque_secret",)
    # And the containment that actually applies still applies: harvest drops
    # `RecordedCall.key` from the payload before the output scan reads it.
    payload: dict[str, list[dict[str, str]]] = {
        "model_calls": [{"key": DIGEST, "request": "summarise the passage"}]
    }
    assert policy.find(payload) == ("opaque_secret",)
    for call in payload["model_calls"]:
        call.pop("key")
    assert policy.find(payload) == ()


def test_a_uuid_shaped_slug_of_english_is_not_a_uuid() -> None:
    """The nearest miss to ADR 0126's false positive: every group hex-only and
    length-exact is what keeps English out."""
    policy = RedactionPolicy()
    for text in (
        "billing1-2026-week-0912-abcdefghijkl",  # right group lengths, wrong alphabet
        "deadbeef-abcd-abcd-abcd-abcdefghijkl",  # trailing group is not hex
        "7e16b0b-b75a-4a16-9765-839cf1b96755",  # first group is 7, not 8
    ):
        assert "uuid" not in policy.find({"o": text}), text


def test_the_harness_own_run_id_is_dropped_from_the_scan_but_a_typed_one_is_not() -> None:
    """The seam ADR 0197 opened and closed in the same increment.

    A run id is a `uuid4` the harness assigns, so once `uuid` became a pattern
    EVERY harvest of a recorded run was rejected "a secret survived redaction"
    — the same failure ADR 0126 hit with the cassette digest, one field over
    (`tests/cli/test_run.py::test_a_recorded_run_re_executes_identically_and_is_harvested`
    is where it surfaced). The fix drops two exact field paths; it does not
    teach the pattern to ignore the shape, so a UUID the tenant typed into the
    objective is still caught.
    """
    from aef.harness.harvest import _HARNESS_IDENTIFIERS, _scannable

    assert _HARNESS_IDENTIFIERS == (("id",), ("initial_state", "run_id"))

    run_id = "40593bcd-c7be-4341-9dc4-94bcf83d3e6c"
    typed = "7e16b0bb-b75a-4a16-9765-839cf1b96755"
    policy = RedactionPolicy()

    harness_only = {"id": run_id, "initial_state": {"run_id": run_id, "objective": "summarise"}}
    assert policy.find(harness_only) == ("uuid",)
    for path in _HARNESS_IDENTIFIERS:
        node = harness_only
        for key in path[:-1]:
            node = node[key]  # type: ignore[assignment]
        node.pop(path[-1])
    assert policy.find(harness_only) == ()

    # The control: the same drop must NOT hide one the tenant typed.
    tenant = {
        "id": run_id,
        "initial_state": {"run_id": run_id, "objective": f"reconcile subscription {typed}"},
    }
    for path in _HARNESS_IDENTIFIERS:
        node = tenant
        for key in path[:-1]:
            node = node[key]  # type: ignore[assignment]
        node.pop(path[-1])
    assert policy.find(tenant) == ("uuid",)
    assert _scannable is not None  # the real caller, exercised in tests/cli/test_run.py


def test_every_pattern_has_a_planted_positive_in_this_file() -> None:
    """The mutation guard: adding a pattern with no sample here is the state
    ADR 0197 exists to end, and removing one makes its sample fail above."""
    sampled = {label for label, _ in PLANTED}
    # `email`, `bearer` and `opaque_secret` are sampled by test_redaction.py.
    inherited = {"email", "bearer", "opaque_secret"}
    declared = {label for label, _ in DEFAULT_PATTERNS}
    assert declared == sampled | inherited, declared.symmetric_difference(sampled | inherited)
