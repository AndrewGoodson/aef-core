"""Milestone 1's acceptance tests.

The central claim is "a panel with no data cannot render green." That is a
claim about a type, so one of these tests runs `mypy` on a snippet and asserts
it is REJECTED — the property is that the compiler stops you, and a test that
only checked runtime behaviour would pass just as happily against a convention
somebody could forget.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import pytest

from aef.dash.contract import (
    FIELD_DISCLOSURE,
    FORBIDDEN_HTML_CONSTRUCTS,
    PANELS,
    PANELS_BY_KEY,
    Disclosure,
    DisclosureError,
    Known,
    Panel,
    PanelSpec,
    PanelState,
    Unknown,
    UnknownReason,
    disclosure_of,
    panel_spec,
    prepare,
)
from aef.harness.monitoring import Digest, evaluate_window

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# 1b — a panel with no data cannot render green.
# --------------------------------------------------------------------------


def test_unknown_has_no_state_attribute_at_all() -> None:
    """The structural half. There is no attribute to read, so there is no
    branch in which an empty panel produces HEALTHY."""
    unknown = Unknown(reason=UnknownReason.NO_LEDGER)
    assert not hasattr(unknown, "state")
    assert "state" not in vars(unknown)


def test_known_refuses_to_hold_the_unknown_state() -> None:
    with pytest.raises(ValueError, match="contradiction"):
        Known(value=1, state=PanelState.UNKNOWN)


def test_no_panel_and_no_declared_reason_combination_renders_green() -> None:
    """Exhaustive over every panel and every reason that panel declares — not
    a sample. The whole program's stated lesson is that the sampled check is
    the one that misses.

    Scoped to DECLARED reasons since round 2, because an undeclared reason is
    now refused outright; the test below covers that half.
    """
    checked = 0
    for spec in PANELS:
        for reason in spec.unknown_when:
            panel = Panel(spec=spec, reading=Unknown(reason=reason))
            assert panel.state is PanelState.UNKNOWN, (spec.key, reason)
            assert panel.is_green is False, (spec.key, reason)
            checked += 1
    assert checked == sum(len(spec.unknown_when) for spec in PANELS)
    assert checked >= len(PANELS), "every panel contributed at least one case"


def test_every_undeclared_pairing_is_refused_rather_than_rendered() -> None:
    """The other half of the product. Together these two cover all
    len(PANELS) x len(UnknownReason) pairs with no gap."""
    refused = 0
    for spec, reason in product(PANELS, UnknownReason):
        if reason in spec.unknown_when:
            continue
        with pytest.raises(ValueError, match="cannot be unknown for reason"):
            Panel(spec=spec, reading=Unknown(reason=reason))
        refused += 1
    total = len(PANELS) * len(UnknownReason)
    declared = sum(len(spec.unknown_when) for spec in PANELS)
    assert refused + declared == total, "the two tests must partition the product exactly"


def test_known_panels_do_report_their_state() -> None:
    """The control for the test above: if Panel always returned UNKNOWN it
    would pass every assertion so far and be useless."""
    healthy = Panel(
        spec=panel_spec("acceptance"), reading=Known(value=0.5, state=PanelState.HEALTHY)
    )
    degraded = Panel(
        spec=panel_spec("acceptance"), reading=Known(value=0.0, state=PanelState.DEGRADED)
    )
    assert healthy.state is PanelState.HEALTHY
    assert healthy.is_green is True
    assert degraded.state is PanelState.DEGRADED
    assert degraded.is_green is False


def test_mypy_rejects_reading_state_without_narrowing() -> None:
    """The claim is that the TYPE stops you, so run the type checker.

    Asserting on runtime behaviour would prove only that today's code happens
    not to do it. This proves the next person cannot.
    """
    snippet = REPO_ROOT / "build" / "dash_narrowing_check.py"
    snippet.parent.mkdir(parents=True, exist_ok=True)
    snippet.write_text(
        "from aef.dash.contract import Reading\n"
        "\n"
        "\n"
        "def is_green(reading: Reading[int]) -> bool:\n"
        "    return reading.state == 'healthy'\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--strict", str(snippet)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode != 0, (
            "mypy ACCEPTED an unnarrowed `.state` access on a Reading. The 'panel with no "
            f"data cannot render green' property is a convention, not a type.\n{result.stdout}"
        )
        assert "state" in result.stdout, result.stdout
    finally:
        snippet.unlink(missing_ok=True)


def test_mypy_accepts_the_narrowed_form() -> None:
    """The control. If the snippet above failed for an unrelated reason — a
    bad import, a syntax error — the test would pass while proving nothing."""
    snippet = REPO_ROOT / "build" / "dash_narrowing_ok.py"
    snippet.parent.mkdir(parents=True, exist_ok=True)
    snippet.write_text(
        "from aef.dash.contract import Known, Reading\n"
        "\n"
        "\n"
        "def is_green(reading: Reading[int]) -> bool:\n"
        "    if isinstance(reading, Known):\n"
        "        return reading.state == 'healthy'\n"
        "    return False\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--strict", str(snippet)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, (
            f"the narrowed form should type-check; if it does not, the previous test's "
            f"failure proves nothing about narrowing.\n{result.stdout}"
        )
    finally:
        snippet.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# The three defects this milestone's adversarial round reproduced.
# Each is built from the REAL API, never a paraphrase of it.
# --------------------------------------------------------------------------


def test_a_real_digest_with_no_proposals_cannot_produce_a_green_panel() -> None:
    """The attack that defeated the module's central claim in four lines.

    Deliberately constructed from the actual `Digest`, not from a literal
    `None` — the point is that a real, shipped source in this repo hands you
    the value that broke it. Twice in the predecessor program a detector
    passed its own planted fault and was still wrong, both times because the
    fault was a paraphrase.
    """
    digest = Digest(
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert digest.acceptance_rate is None, "precondition: zero proposals means None"

    with pytest.raises(ValueError, match="Unknown case wearing an Optional"):
        Known(value=digest.acceptance_rate, state=PanelState.HEALTHY)


def test_known_optional_is_the_correct_spelling_and_it_works_both_ways() -> None:
    """Refusing None without offering the right spelling just relocates the
    mistake to `Known(value=x or 0, ...)`."""
    digest = Digest(
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 2, 1, tzinfo=UTC),
    )
    absent = Known.optional(
        digest.acceptance_rate,
        PanelState.HEALTHY,
        reason=UnknownReason.LEDGER_EMPTY,
    )
    assert isinstance(absent, Unknown)
    assert absent.reason is UnknownReason.LEDGER_EMPTY
    assert Panel(spec=panel_spec("acceptance"), reading=absent).is_green is False

    present = Known.optional(0.75, PanelState.HEALTHY, reason=UnknownReason.LEDGER_EMPTY)
    assert isinstance(present, Known)
    assert Panel(spec=panel_spec("acceptance"), reading=present).is_green is True


def test_the_other_optional_sources_are_the_same_trap() -> None:
    """Named in the error message, so they are named in a test. Each returns
    `X | None` where None means 'nothing to compare'."""
    digest = Digest(
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert digest.beating_manual_editing is None
    with pytest.raises(ValueError, match="Unknown case wearing an Optional"):
        Known(value=digest.beating_manual_editing, state=PanelState.HEALTHY)

    merged_at = datetime(2026, 1, 10, tzinfo=UTC)
    result = evaluate_window(
        [],
        baseline_pass_rate=0.9,
        merged_at=merged_at,
        now=merged_at,
    )
    assert result.observed_pass_rate is None
    with pytest.raises(ValueError, match="Unknown case wearing an Optional"):
        Known(value=result.observed_pass_rate, state=PanelState.HEALTHY)


def test_a_bare_string_state_is_refused_because_panelstate_is_a_strenum() -> None:
    """`PanelState` members ARE strings, so `state="unknown"` compared unequal
    to every member under `is` and slipped past the contradiction guard."""
    assert isinstance(PanelState.HEALTHY, str), "precondition: StrEnum"
    assert (PanelState.UNKNOWN == "unknown") is True
    # Bound to a name rather than written inline: ruff's F632 autofix rewrites
    # `"unknown" is PanelState.UNKNOWN` into `==`, which inverts the very gap
    # this line documents. A linter silently changing what an assertion proves
    # is worth the two extra characters.
    raw_state = "unknown"
    assert (raw_state is PanelState.UNKNOWN) is False, "precondition: the identity gap"

    with pytest.raises(TypeError, match="must be a PanelState"):
        Known(value=1, state="unknown")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be a PanelState"):
        Known(value=1, state="healthy")  # type: ignore[arg-type]


def test_an_arbitrary_object_with_a_state_attribute_cannot_be_a_reading() -> None:
    """Duck typing at a trust boundary: anything carrying `.state = HEALTHY`
    rendered green, because the else-branch trusted what it was handed."""

    @dataclass(frozen=True)
    class Impostor:
        state: PanelState = PanelState.HEALTHY

    with pytest.raises(TypeError, match="must be Unknown or Known"):
        Panel(spec=panel_spec("halt"), reading=Impostor())  # type: ignore[arg-type]


def test_an_empty_collection_is_still_data() -> None:
    """The boundary case, decided deliberately rather than by omission: empty
    is not absent. Zero recorded errors IS healthy, and refusing `[]` the way
    `None` is refused would force callers to report UNKNOWN for a question
    they can actually answer."""
    panel = Panel(spec=panel_spec("runs"), reading=Known(value=[], state=PanelState.HEALTHY))
    assert panel.is_green is True


# --------------------------------------------------------------------------
# 1a — every panel names what makes it UNKNOWN.
# --------------------------------------------------------------------------


def test_every_panel_declares_an_unknown_condition() -> None:
    for spec in PANELS:
        assert spec.unknown_when, spec.key


def test_a_panel_claiming_it_cannot_be_unknown_is_refused() -> None:
    with pytest.raises(ValueError, match="declares no UNKNOWN condition"):
        PanelSpec(key="wishful", title="Wishful", watches="nothing", unknown_when=())


def test_panel_keys_are_unique() -> None:
    keys = [spec.key for spec in PANELS]
    assert len(keys) == len(set(keys))


def test_a_panel_refuses_an_unknown_reason_its_spec_never_declared() -> None:
    """Round 2: `unknown_when` was documentation and nothing checked it, so
    the halt panel reported `corpus_empty` — sending the operator to fix the
    corpus while the loop was halted."""
    spec = panel_spec("halt")
    assert UnknownReason.CORPUS_EMPTY not in spec.unknown_when, "precondition"
    with pytest.raises(ValueError, match="cannot be unknown for reason"):
        Panel(spec=spec, reading=Unknown(reason=UnknownReason.CORPUS_EMPTY))

    # ...and the reason it DOES declare still works.
    ok = Panel(spec=spec, reading=Unknown(reason=UnknownReason.NO_LOOP_STATE))
    assert ok.state is PanelState.UNKNOWN


def test_every_unknown_reason_has_a_panel_that_can_show_it() -> None:
    """Round 2 found four members no panel declared, including the most
    security-relevant one. A reason with no home is a case that can be
    computed and never displayed — ADR 0101's rule ("a declared thing with no
    caller reads as a present feature") applied to this module's own enum."""
    declared = {reason for spec in PANELS for reason in spec.unknown_when}
    orphans = sorted(r.value for r in UnknownReason if r not in declared)
    assert not orphans, (
        f"UnknownReason members no panel can display: {orphans}. Either give one a panel "
        f"or delete it until the milestone that needs it — the fleet reasons were removed "
        f"for exactly this and return in Milestone 4."
    )


def test_a_chain_nobody_checked_is_not_a_chain_that_passed() -> None:
    """The ledger panel must be able to say "not verified" — distinct from a
    verification that FAILED, which is Known(DEGRADED) and loud."""
    spec = panel_spec("ledger_integrity")
    assert UnknownReason.LEDGER_NOT_VERIFIED in spec.unknown_when
    panel = Panel(spec=spec, reading=Unknown(reason=UnknownReason.LEDGER_NOT_VERIFIED))
    assert panel.is_green is False

    failed = Panel(spec=spec, reading=Known(value=False, state=PanelState.DEGRADED))
    assert failed.state is PanelState.DEGRADED
    assert failed.is_green is False


def test_a_known_subclass_that_skips_its_guard_is_still_caught_at_the_panel() -> None:
    """Defence in depth. Not because a malicious subclass is the threat model,
    but because the zone rule survived three defeats of the allowlist by not
    being the only check (ADR 0093)."""

    class Unguarded(Known[object]):
        def __post_init__(self) -> None:
            return None

    with pytest.raises(ValueError, match="holds Known\\(value=None\\)"):
        Panel(spec=panel_spec("runs"), reading=Unguarded(value=None, state=PanelState.HEALTHY))


def test_unknown_reason_must_be_an_enum_member() -> None:
    """Free text here would defeat the routing the enum exists for."""
    with pytest.raises(TypeError, match="UnknownReason"):
        Unknown(reason="the ledger is missing I think")  # type: ignore[arg-type]


def test_panel_spec_lookup_names_the_alternatives() -> None:
    with pytest.raises(KeyError, match="known panels are"):
        panel_spec("no_such_panel")


# --------------------------------------------------------------------------
# 1d — no field is emitted whose disclosure nobody decided.
# --------------------------------------------------------------------------


def test_unregistered_field_raises_rather_than_defaulting() -> None:
    with pytest.raises(DisclosureError, match="no disclosure decision"):
        disclosure_of("some_field_added_next_tuesday")


def test_the_secrets_are_excluded() -> None:
    """Named explicitly. A test over the whole dict would pass if every entry
    were PUBLIC; these are the ones whose value is the point."""
    for field in (
        "signing_key",
        "canary_salt",
        "canary_salt_fingerprint",
        "api_key",
        "environment",
        "prompt_text",
        "response_text",
        "tool_arguments",
        "working_memory",
        "retrieved_context",
        "repo_root",
        "state_dir",
    ):
        assert disclosure_of(field) is Disclosure.EXCLUDED, field
        with pytest.raises(DisclosureError, match="EXCLUDED"):
            prepare(field, "whatever")


def test_the_salt_fingerprint_is_excluded_and_the_salt_is_too() -> None:
    """ADR 0106 made the fingerprint a 200k-iteration PBKDF2 because it is an
    offline oracle against the salt. An export is a file that gets pasted
    around; putting the fingerprint in one hands over the oracle and the
    leisure to grind it."""
    assert disclosure_of("canary_salt_fingerprint") is Disclosure.EXCLUDED
    assert disclosure_of("canary_salt") is Disclosure.EXCLUDED
    # But the fact that keying is on is exactly what an operator must see.
    assert disclosure_of("canary_keyed") is Disclosure.PUBLIC


def test_error_message_is_redacted_but_its_shape_is_not() -> None:
    """The operator's question is "is it failing, and how" — answered by type
    and count. The message is the field most likely to stringify a connection
    URL or an echoed Authorization header."""
    assert disclosure_of("error_message") is Disclosure.REDACTED
    assert disclosure_of("error_type") is Disclosure.PUBLIC
    assert disclosure_of("error_count") is Disclosure.PUBLIC


def test_tenant_tags_are_redacted() -> None:
    """A tenant tag list in a shared file is a customer list."""
    assert disclosure_of("tenant_tag") is Disclosure.REDACTED
    assert disclosure_of("tenant_count") is Disclosure.PUBLIC


def test_every_registered_field_has_a_real_disclosure() -> None:
    for field, value in FIELD_DISCLOSURE.items():
        assert isinstance(value, Disclosure), field


# --------------------------------------------------------------------------
# Round 3. Two mutable registries, and an API whose name lied.
# --------------------------------------------------------------------------


def test_the_disclosure_registry_cannot_be_rewritten_at_runtime() -> None:
    """It was a plain dict, so `FIELD_DISCLOSURE["signing_key"] =
    Disclosure.PUBLIC` flipped an EXCLUDED field to PUBLIC. Deciding a
    disclosure and leaving the decision writable is most of the way back to
    not having decided."""
    assert disclosure_of("signing_key") is Disclosure.EXCLUDED
    with pytest.raises((TypeError, AttributeError)):
        FIELD_DISCLOSURE["signing_key"] = Disclosure.PUBLIC  # type: ignore[index]
    assert disclosure_of("signing_key") is Disclosure.EXCLUDED


def test_the_panel_registry_cannot_be_widened_at_runtime() -> None:
    """One assignment switched off the enforcement round 2 had just added."""
    with pytest.raises((TypeError, AttributeError)):
        PANELS_BY_KEY["halt"] = PanelSpec(  # type: ignore[index]
            key="halt", title="t", watches="w", unknown_when=tuple(UnknownReason)
        )
    assert panel_spec("halt").unknown_when == (UnknownReason.NO_LOOP_STATE,)


def test_prepare_refuses_an_excluded_field_outright() -> None:
    with pytest.raises(DisclosureError, match="EXCLUDED and must not be emitted"):
        prepare("signing_key", "sk-live-abc123")


def test_prepare_redacts_the_two_fields_that_carry_secrets() -> None:
    """The defect this replaced: `emittable()` returned True for REDACTED, so
    the obvious caller — `if emittable(f): payload[f] = value` — emitted the
    raw error message and the raw tenant tag. Built from a connection string
    of the exact shape a traceback stringifies, not a paraphrase."""
    secret = "postgres://user:hunter2@db.internal/prod"
    out = prepare("error_message", secret)
    assert secret not in str(out)
    assert "hunter2" not in str(out)
    assert str(out).startswith("sha256:")

    tag = prepare("tenant_tag", "acme-corp")
    assert "acme" not in str(tag)


def test_prepare_passes_public_values_through_unchanged() -> None:
    """The control. A `prepare` that redacted everything would pass every
    assertion above and make the export useless."""
    assert prepare("merged", 7) == 7
    assert prepare("ledger_verified", True) is True
    assert prepare("graph_id", "billing-agent") == "billing-agent"


def test_redaction_is_stable_so_the_fleet_page_can_still_count() -> None:
    """Grouping identical errors and counting distinct tenants is the whole
    reason this is a digest rather than a constant placeholder."""
    assert prepare("tenant_tag", "acme") == prepare("tenant_tag", "acme")
    assert prepare("tenant_tag", "acme") != prepare("tenant_tag", "globex")


def test_emittable_is_gone() -> None:
    """It is not deprecated, it is removed. A boolean over a three-valued
    policy reads as 'safe to emit' at every call site, and leaving it importable
    would keep that reading available."""
    import aef.dash.contract as contract

    assert not hasattr(contract, "emittable")


# --------------------------------------------------------------------------
# 1c — read-only.
# --------------------------------------------------------------------------


def test_forbidden_constructs_cover_the_four_ways_to_get_a_write() -> None:
    """Not a spelling test: each of these is a distinct mechanism, and a list
    that covered only `<form>` would miss the three that matter more."""
    joined = " ".join(FORBIDDEN_HTML_CONSTRUCTS)
    assert "<form" in joined  # classic submit
    assert "<button" in joined  # scripted handler
    assert "fetch(" in joined  # background request
    assert "XMLHttpRequest" in joined  # the older background request
    assert "navigator.sendBeacon" in joined  # the one people forget
    assert "WebSocket" in joined  # the persistent one
